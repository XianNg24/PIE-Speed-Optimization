"""
PIE (Performance-Improving Edits) sample loader.

Reads pairs of (slow, fast) C++ submissions from pie-perf JSONL splits and
attaches public test cases from input.N.txt / output.N.txt files.

Each yielded sample mirrors the schema in data/bugs.py with one extension:
  source             = "pie"
  test_cases         = [{"input": str, "expected_output": str}, ...]
  problem_id         = "p03146"
  problem_statement  = "..."   (extracted from problem_statements_translated.zip
                                when available; None otherwise)
  improvement_frac, cpu_time_v0, cpu_time_v1   (metadata)

The 'buggy_code' is the slow version (status_v0 = Accepted, but slower).
The 'fixed_code' is the gold faster version (status_v1 = Accepted).
"""
import json
import os
import re
import sys
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

from config import PIE_SPLIT_TEST, PIE_TESTCASES_DIR, PIE_MERGED_TESTCASES_DIR

# ─── Problem statement extraction ────────────────────────────────────────────
_STMT_ZIP_PATH = os.path.join(
    _PROJECT, "pie-perf", "data", "problem_statements_translated.zip",
)
_STMT_INNER_PREFIX = (
    "usr1/amadaan/learning2perf/project_codenet/Project_CodeNet/"
    "problem_descriptions_translated/"
)

_stmt_cache = {}
_stmt_zip = None


def _strip_html(raw: str) -> str:
    """Convert problem-statement HTML to plain text via regex."""
    s = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", s,
               flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</p\s*>|</div\s*>|</li\s*>|</h[1-6]\s*>", "\n", s,
               flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    entities = {"&nbsp;": " ", "&lt;": "<", "&gt;": ">", "&amp;": "&",
                "&quot;": '"', "&#39;": "'", "&apos;": "'"}
    for k, v in entities.items():
        s = s.replace(k, v)
    # Collapse internal whitespace; preserve one blank line between paragraphs.
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def extract_constraints_section(full_text: str):
    """
    Pull just the 'Constraints' section out of a full problem statement.

    Returns the constraints text, or None if no Constraints heading is found.
    Stops at the next major heading (Input / Output / Sample Input/Output /
    Notes / Example), or at end of text.
    """
    if not full_text:
        return None
    # Be permissive about the heading: standalone word on its own line.
    start = re.search(r"(?:^|\n)\s*Constraints\s*\n", full_text,
                       flags=re.IGNORECASE)
    if not start:
        return None
    tail = full_text[start.end():]
    # Stop at the next major section heading.
    end = re.search(
        r"(?:^|\n)\s*(Input|Output|Sample Input|Sample Output|Notes|Example|"
        r"Partial Score|Score|Hint)\b",
        tail, flags=re.IGNORECASE,
    )
    section = tail[:end.start()] if end else tail
    section = re.sub(r"[ \t]+", " ", section)
    section = re.sub(r"\n{3,}", "\n\n", section).strip()
    return section if section else None


def get_problem_statement(problem_id: str, max_chars: int = 4000,
                          constraints_only: bool = True):
    """
    Return a plain-text problem statement for `problem_id`, or None if not
    available. Lazy-loads and caches per-problem.

    With `constraints_only=True` (default), returns just the Constraints
    section (the literal numeric bounds that 7B models can exploit). Falls
    back to the full statement if no Constraints heading is found.
    """
    cache_key = (problem_id, constraints_only)
    global _stmt_zip
    if cache_key in _stmt_cache:
        return _stmt_cache[cache_key]
    if _stmt_zip is None:
        _stmt_zip = (zipfile.ZipFile(_STMT_ZIP_PATH)
                     if os.path.exists(_STMT_ZIP_PATH) else False)
    if _stmt_zip is False:
        _stmt_cache[cache_key] = None
        return None
    name = f"{_STMT_INNER_PREFIX}{problem_id}.html"
    try:
        raw = _stmt_zip.read(name).decode("utf-8", errors="replace")
    except KeyError:
        _stmt_cache[cache_key] = None
        return None
    full_text = _strip_html(raw)
    if constraints_only:
        text = extract_constraints_section(full_text)
        if not text:
            # No Constraints heading recognised; suppress entirely so the
            # model isn't fed unfiltered prose by accident.
            _stmt_cache[cache_key] = None
            return None
        # Prepend a small label so the LLM knows what this block is.
        text = "Constraints:\n" + text
    else:
        text = full_text
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n[... truncated]"
    _stmt_cache[cache_key] = text
    return text


def _read_cases_from_dir(pdir: str) -> list:
    """Read all input.N.txt / output.N.txt pairs from a single directory."""
    if not os.path.isdir(pdir):
        return []
    cases = []
    indices = sorted({
        int(f.split(".")[1]) for f in os.listdir(pdir)
        if f.startswith("input.") and f.endswith(".txt")
    })
    for i in indices:
        in_path  = os.path.join(pdir, f"input.{i}.txt")
        out_path = os.path.join(pdir, f"output.{i}.txt")
        if not (os.path.exists(in_path) and os.path.exists(out_path)):
            continue
        with open(in_path)  as fi: stdin_data  = fi.read()
        with open(out_path) as fo: expected    = fo.read()
        cases.append({"input": stdin_data, "expected_output": expected})
    return cases


def _load_test_cases(problem_id: str,
                     merged_dir: str = PIE_MERGED_TESTCASES_DIR,
                     public_dir: str = PIE_TESTCASES_DIR,
                     max_cases: int = None) -> list:
    """
    Read test cases for a problem, preferring the larger merged_test_cases
    set when it has cases for this problem, falling back to public_test_cases
    otherwise.

    `max_cases` caps the returned list (deterministic — keeps the lowest
    indices). None = no cap.
    """
    cases = _read_cases_from_dir(os.path.join(merged_dir, problem_id))
    if not cases:
        cases = _read_cases_from_dir(os.path.join(public_dir, problem_id))
    if max_cases is not None and len(cases) > max_cases:
        cases = cases[:max_cases]
    return cases


def load_pie_samples(jsonl_path: str = PIE_SPLIT_TEST,
                     n: int = 5,
                     min_improvement: float = 30.0,
                     max_lines: int = 80,
                     min_cpu_time_v0: float = 0.0,
                     skip: int = 0,
                     unique_problems: bool = True,
                     problem_statement_constraints_only: bool = True,
                     max_test_cases: int = None) -> list:
    """
    Pick `n` PIE samples from `jsonl_path` that meet the filters.

    Filters keep this practical for an experimental run:
      - improvement_frac >= min_improvement   (meaningful speedup target)
      - slow code is at most `max_lines` non-empty LOC (easy for LLM context)
      - cpu_time_v0 >= min_cpu_time_v0        (CodeNet judge time, ms-ish; bigger
                                               values give gprof real signal)
      - both versions are 'Accepted'
      - the problem has at least one public test case
      - unique_problems=True keeps at most one sample per problem_id
    """
    out = []
    seen = 0
    used_problems = set()
    with open(jsonl_path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("status_v0") != "Accepted" or r.get("status_v1") != "Accepted":
                continue
            if (r.get("improvement_frac") or 0) < min_improvement:
                continue
            v0_loc = r.get("code_v0_loc") or 0
            if v0_loc > max_lines:
                continue
            if (r.get("cpu_time_v0") or 0) < min_cpu_time_v0:
                continue
            if unique_problems and r["problem_id"] in used_problems:
                continue
            tcs = _load_test_cases(r["problem_id"], max_cases=max_test_cases)
            if not tcs:
                continue
            seen += 1
            if seen <= skip:
                continue
            used_problems.add(r["problem_id"])

            out.append({
                "id": f"pie_{r['problem_id']}_{r['submission_id_v0']}",
                "source": "pie",
                "bug_type": "performance",
                "description": (
                    f"PIE: speed up CodeNet problem {r['problem_id']} "
                    f"(v0 cpu_time={r['cpu_time_v0']}, "
                    f"v1 cpu_time={r['cpu_time_v1']}, "
                    f"improvement_frac={r['improvement_frac']:.1f}%)"
                ),
                "buggy_code": r["input"],          # the slow version
                "fixed_code": r["target"],         # the gold faster version
                "test_cases": tcs,
                "problem_id": r["problem_id"],
                "problem_statement": get_problem_statement(
                    r["problem_id"],
                    constraints_only=problem_statement_constraints_only,
                ),
                "cpu_time_v0": r["cpu_time_v0"],
                "cpu_time_v1": r["cpu_time_v1"],
                "improvement_frac": r["improvement_frac"],
            })
            if len(out) >= n:
                break
    return out


if __name__ == "__main__":
    samples = load_pie_samples(n=3)
    print(f"Loaded {len(samples)} PIE samples")
    for s in samples:
        print(f"  {s['id']:<40} tests={len(s['test_cases'])}  "
              f"v0={s['cpu_time_v0']}  v1={s['cpu_time_v1']}  "
              f"+{s['improvement_frac']:.0f}%")
