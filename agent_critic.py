"""
Critic agent — diagnoses why a candidate failed and emits a structured
note that downstream Planner / Coder calls can act on.

Currently the self-repair retry bounces the raw stdout diff back to the
optimiser, which leaves the model to re-diagnose the failure from scratch
on every round. Empirically (see results/run_20260616-165542_threetier/
error_report.md) the failure classes are stereotyped — off-by-one in DP,
broken tie-break, missing edge case, etc. — and naming the class up-front
should let the next Planner pass aim at the actual mistake.

The Critic takes:
  - the failed candidate's source
  - up to 3 failing (input, expected, actual) triples
  - the previous plan that produced this candidate (so it can see whether
    the failure is "the plan was implemented wrong" vs "the plan itself is
    bad")

It returns a structured dict:
  {
    "failure_class":  <one short tag e.g. "off_by_one">,
    "evidence":       <one sentence pointing at the smallest concrete clue>,
    "suggested_fix":  <one sentence — concrete next change for the Coder>,
    "plan_was_wrong": <bool — true if the plan itself, not the code, is at fault>,
  }

Per-`critic_id` disk cache, keyed by `(sample_id, candidate_hash)`. Same
pattern as `data/complexity_predictor.py` so cache invalidation rules are
familiar.
"""
import csv
import hashlib
import json
import os
import re
import sys
from typing import Optional, Callable

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# Closed taxonomy of failure classes. The Critic must pick one; if none
# fit it returns "other" + free-text in `evidence`.
#
# v2 (this file): the v1 anchor labels "wrong_base_case" and "wrong_state_dim"
# absorbed 78% of all critic outputs in run_20260623-160426 regardless of
# actual failure cause. Splitting them into specific sub-classes forces the
# Critic to pick a more precise diagnosis instead of pattern-matching to a
# generic-sounding label.
FAILURE_CLASSES = [
    "off_by_one",                # i<n vs i<=n; len-1 vs len; etc.
    "wrong_loop_bound",          # loop runs too few / too many times
    "wrong_initial_value",       # dp[0]=0 vs INF; accumulator seed wrong
    "missing_state_dimension",   # memo / DP key missing a state component
    "wrong_iteration_order",     # DP fill order; topological order wrong
    "wrong_comparator",          # sort / set / priority order inverted
    "tie_break_inverted",        # equal keys ordered wrong (specific tie-break)
    "index_out_of_bounds",       # array/vector access past end (usually runtime)
    "missing_edge_case",         # n=0, empty input, single-element, overflow
    "io_format_drift",           # extra newline, wrong separator, endl mismatch
    "logic_error",               # condition flipped, operator wrong
    "container_misuse",          # wrong iteration, invalidated iterator
    "compile_error",             # candidate didn't compile
    "plan_unsuitable",           # the plan itself can't work given constraints
    "other",
]


# Critic prompt v2. Two changes versus v1:
#   1. Asks for a `replacement_block` (a small C++ patch the next optimiser
#      pass is told to apply *literally*), not a free-text `suggested_fix`.
#      Wins on p00596 in run_20260623-160426 came from literal suggestions
#      like "Add cin.eof() check"; vague suggestions like "ensure state
#      dimension is properly managed" produced no wins. We bias toward
#      operationalisable fixes.
#   2. Asks the Critic to consider plan validity *separately* from code
#      correctness, with an explicit "if the plan is impossible given the
#      stated constraints, set plan_was_wrong=true" clause — addressing the
#      0/123 rate at which v1 ever blamed the plan.
_CRITIC_PROMPT_V2 = """You are an expert C++ code reviewer for a competitive-programming optimisation pipeline.
A code-generation model was asked to produce a faster version of a slow but
correct C++ program. The result FAILED. Your job is to (a) NAME the failure
class and (b) emit a small, concrete CODE EDIT that the next attempt should
apply LITERALLY.

The slow program is ALREADY CORRECT — code-level failures here mean the
rewrite broke something the slow version handled. However:
  - If the plan ITSELF prescribes something that cannot work given the
    problem's stated constraints (e.g. counting sort on values up to 10^9,
    a recurrence that ignores a needed state dimension), set
    plan_was_wrong=true and say so in `evidence`.

Previous plan that guided the failed attempt:
---
{prev_plan}
---

Failed candidate code:
```cpp
{failed_code}
```

Concrete failure evidence (up to {n_cases} test case(s); a minimal failing
input has been extracted by delta-debugging where possible):
{cases_block}

Pick EXACTLY ONE class from this closed list (no synonyms, no new labels):
{taxonomy}

Output ONLY the JSON object below. The replacement_block must be a small
C++ snippet that can be applied literally — prefer 2-10 lines that REPLACE
a specific section of the failed code, not the whole program. If a
single-line change is enough, that single line is the replacement_block.

{{"failure_class": "<class>", "evidence": "<one short sentence pointing at the smallest concrete clue, e.g. naming the variable, line, or input value where divergence happens>", "replacement_block": "<small C++ code that the next attempt should incorporate literally — keep it minimal>", "plan_was_wrong": <true if the PLAN itself is at fault, false if the plan was sound but the code mis-implemented it>}}
"""


def _cache_path(critic_id: str) -> str:
    return os.path.join(_HERE, "data", f"critic_{critic_id}.csv")


def _candidate_hash(code: str) -> str:
    """Short hash so cache rows stay readable; collisions are tolerable."""
    return hashlib.sha1(code.encode("utf-8", errors="replace")).hexdigest()[:12]


def _load_cache(path: str) -> dict:
    cache = {}
    if not os.path.exists(path):
        return cache
    with open(path, newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0 and row and row[0] == "sample_id":
                continue
            if len(row) >= 4:
                # key = (sample_id, candidate_hash) → JSON string of diagnosis
                cache[(row[0], row[1])] = row[3]
    return cache


def _append_cache(path: str, sample_id: str, cand_hash: str,
                  failure_class: str, diagnosis_json: str):
    is_new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["sample_id", "candidate_hash", "failure_class",
                        "diagnosis_json"])
        w.writerow([sample_id, cand_hash, failure_class, diagnosis_json])


def _format_cases_block(failing_tests: list, n_show: int = 3,
                        per_case_cap: int = 300) -> str:
    """Render the per-test failure evidence into the prompt."""
    out = []
    shown = 0
    for t in failing_tests:
        if shown >= n_show:
            break
        if t.get("passed"):
            continue
        # Prefer the shrunk (delta-debugged) input when available — it is
        # the smallest stdin we could find that still produces a wrong
        # answer. Use the original input as fallback. Same for outputs.
        stdin = ((t.get("shrunk_input") or t.get("input") or "")
                 .strip()[:200])
        expected = ((t.get("shrunk_expected") or t.get("expected") or "")
                    .strip()[:per_case_cap])
        actual = ((t.get("shrunk_actual") or t.get("stdout") or "")
                  .strip()[:per_case_cap])
        shrunk_tag = (" (delta-debugged minimal)"
                      if t.get("shrunk_input") else "")
        out.append(
            f"  Test #{t.get('idx','?')}{shrunk_tag}:\n"
            f"    Input:    {stdin!r}\n"
            f"    Expected: {expected!r}\n"
            f"    Actual:   {actual!r}"
        )
        shown += 1
    if not out:
        return "  (no per-test detail captured)"
    return "\n".join(out)


# ─── Tool B: shrink_failing_input ────────────────────────────────────────
# Delta-debugging on stdin. Uses v0 (which we know is correct) as the
# oracle for the shrunk inputs — we can't compare against the original
# expected_output because that was for the FULL input. Strategy is
# line-based greedy halving; small but reliable.

_MAX_SHRINK_ITERS = 8         # cap depth, sample inputs are small to start
_SHRINK_RUN_TIMEOUT = 3       # seconds per probe — these are tiny inputs


def _outputs_diverge(a: str, b: str) -> bool:
    """Loose stdout comparison: strip trailing whitespace per line."""
    if a is None or b is None:
        return a != b
    norm = lambda s: "\n".join(line.rstrip() for line in s.strip().splitlines())
    return norm(a) != norm(b)


def shrink_failing_input(v0_bin_path: str,
                         candidate_bin_path: str,
                         failing_stdin: str) -> Optional[tuple]:
    """
    Greedy line-based delta-debug. Returns (shrunk_input, v0_output,
    candidate_output) where running candidate on shrunk_input still
    diverges from v0's output on the same input; or None if no smaller
    failing input was found.

    Both binaries must already exist on disk. We do not compile here.
    """
    try:
        from compiler import run_binary
    except Exception:
        return None

    lines = failing_stdin.splitlines(keepends=True)
    if len(lines) <= 2:
        return None    # nothing to shrink

    current = failing_stdin
    iters_left = _MAX_SHRINK_ITERS
    while iters_left > 0:
        iters_left -= 1
        cur_lines = current.splitlines(keepends=True)
        if len(cur_lines) <= 2:
            break

        mid = len(cur_lines) // 2
        candidates = ["".join(cur_lines[:mid]), "".join(cur_lines[mid:])]
        improved = False
        for sub in candidates:
            if not sub.strip():
                continue
            try:
                v0_res = run_binary(v0_bin_path, sub)
                cand_res = run_binary(candidate_bin_path, sub)
            except Exception:
                continue
            if not (v0_res.success and cand_res.success):
                continue
            if _outputs_diverge(v0_res.stdout, cand_res.stdout):
                current = sub
                improved = True
                break
        if not improved:
            break

    if current == failing_stdin:
        return None

    # Final shrunk results
    try:
        v0_res = run_binary(v0_bin_path, current)
        cand_res = run_binary(candidate_bin_path, current)
        if _outputs_diverge(v0_res.stdout, cand_res.stdout):
            return current, v0_res.stdout, cand_res.stdout
    except Exception:
        pass
    return None


def _enrich_with_shrunk(failing_tests: list, v0_src: str,
                        candidate_src: str, sample_id: str) -> list:
    """
    Try to shrink the first failing test's input. Mutates a copy in-place
    and returns the new list. Compiles both v0 and the candidate once.
    Failures here are silent — the Critic falls back to the original
    inputs if shrinking can't run.
    """
    if not failing_tests:
        return failing_tests
    # Only attempt on the first failing test, and only if its input has
    # multiple lines — otherwise there's nothing meaningful to bisect.
    first = next((t for t in failing_tests if not t.get("passed")), None)
    if not first or not (first.get("input") or ""):
        return failing_tests
    if len((first["input"] or "").splitlines()) < 3:
        return failing_tests

    try:
        from compiler import compile_code
        v0 = compile_code(v0_src, f"critic_shrink_v0_{sample_id[-12:]}")
        cand = compile_code(candidate_src, f"critic_shrink_cand_{sample_id[-12:]}")
        if not (v0.success and cand.success):
            return failing_tests
        shrunk = shrink_failing_input(v0.binary_path, cand.binary_path,
                                       first["input"])
        if not shrunk:
            return failing_tests
        new_input, new_expected, new_actual = shrunk
        # Mutate a shallow copy so we don't poison the caller's dict.
        enriched = list(failing_tests)
        first_copy = dict(first)
        first_copy["shrunk_input"] = new_input
        first_copy["shrunk_expected"] = new_expected
        first_copy["shrunk_actual"] = new_actual
        # Replace the first failing test in the list
        for i, t in enumerate(enriched):
            if t is first:
                enriched[i] = first_copy
                break
        return enriched
    except Exception:
        return failing_tests


def _extract_diagnosis(raw: str) -> dict:
    """
    Parse the Critic's JSON output. The model sometimes wraps in ```json
    fences or prefaces with prose; strip that first.

    v2 schema (current): {failure_class, evidence, replacement_block, plan_was_wrong}.
    Also accepts v1 schema (with `suggested_fix`) so old cache rows from
    qwen7b_v1 stay readable when surfaced for inspection.
    """
    empty = {"failure_class": "other", "evidence": "(empty critic output)",
             "replacement_block": "", "plan_was_wrong": False}
    if not raw:
        return empty
    # Strip ```json fences if present
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    # Or find the first {...} object
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        obj = json.loads(raw)
    except Exception:
        return {"failure_class": "other",
                "evidence": raw.strip()[:300],
                "replacement_block": "",
                "plan_was_wrong": False}
    fc = obj.get("failure_class", "other")
    if fc not in FAILURE_CLASSES:
        fc = "other"
    # Accept either replacement_block (v2) or suggested_fix (v1 fallback).
    rb = obj.get("replacement_block")
    if rb is None:
        rb = obj.get("suggested_fix", "")
    return {
        "failure_class":     fc,
        "evidence":          str(obj.get("evidence", "")).strip()[:400],
        "replacement_block": str(rb).strip()[:1200],
        "plan_was_wrong":    bool(obj.get("plan_was_wrong", False)),
    }


def _local_critic_fn(prompt: str, max_new_tokens: int = 512) -> str:
    # 512 tokens to leave room for a small code patch in replacement_block
    # without runaway. Empirically v1 (256) sometimes got truncated when
    # the model wrote a paragraph before the JSON.
    from local_llm import quick_inference
    return quick_inference(prompt, max_new_tokens=max_new_tokens)


_inmem_cache = {}      # {critic_id: {(sample_id, cand_hash): diagnosis_json}}


def critique(sample_id: str,
             failed_code: str,
             failed_verdict: dict,
             prev_plan: Optional[str] = None,
             *,
             v0_source: Optional[str] = None,
             critic_id: str = "qwen7b_v2",
             critic_fn: Optional[Callable[[str], str]] = None,
             ) -> dict:
    """
    Produce a structured diagnosis for one failed candidate.

    Returns the diagnosis dict (always — never raises). On any failure
    of LLM call or parse, returns a graceful "other" diagnosis so the
    orchestrator can carry on with degraded but non-broken behaviour.

    `v0_source` is optional; when provided, the input-shrinker (tool B)
    will attempt to delta-debug the failing stdin against v0 (which is
    known correct) so the Critic sees a minimal failing input instead of
    the full PIE test case.
    """
    path = _cache_path(critic_id)
    cache = _inmem_cache.setdefault(critic_id, _load_cache(path))
    chash = _candidate_hash(failed_code)
    key = (sample_id, chash)
    if key in cache:
        try:
            d = json.loads(cache[key])
            d["cached"] = True
            return d
        except Exception:
            pass    # fall through to fresh call if cached row is corrupt

    failure_mode = failed_verdict.get("failure_mode") or (
        "compile_error" if not failed_verdict.get("compiled") else "other"
    )
    # Compile errors don't need an LLM — short-circuit with a fixed diagnosis.
    if failure_mode in ("compile_error", "compile"):
        diag = {
            "failure_class": "compile_error",
            "evidence": (failed_verdict.get("compile_error") or "").strip()[:300],
            "replacement_block": "",   # compile errors don't yield a code patch
            "plan_was_wrong": False,
        }
        _append_cache(path, sample_id, chash, diag["failure_class"],
                      json.dumps(diag))
        cache[key] = json.dumps(diag)
        diag["cached"] = False
        return diag

    failing_tests = [t for t in (failed_verdict.get("per_test") or [])
                     if not t.get("passed")]

    # Tool B: shrink the failing input to a minimal example when we have v0.
    if v0_source and failing_tests:
        failing_tests = _enrich_with_shrunk(failing_tests, v0_source,
                                            failed_code, sample_id)

    cases_block = _format_cases_block(failing_tests)
    prompt = _CRITIC_PROMPT_V2.format(
        prev_plan=(prev_plan or "(no prior plan)").strip()[:1200],
        failed_code=failed_code.strip()[:3000],
        n_cases=min(3, len(failing_tests)) or 1,
        cases_block=cases_block,
        taxonomy=", ".join(FAILURE_CLASSES),
    )

    fn = critic_fn or _local_critic_fn
    try:
        raw = fn(prompt)
    except Exception as e:
        diag = {"failure_class": "other",
                "evidence": f"critic call raised: {e}",
                "replacement_block": "",
                "plan_was_wrong": False}
        cache[key] = json.dumps(diag)
        _append_cache(path, sample_id, chash, diag["failure_class"],
                      json.dumps(diag))
        diag["cached"] = False
        return diag

    diag = _extract_diagnosis(raw)
    cache[key] = json.dumps(diag)
    _append_cache(path, sample_id, chash, diag["failure_class"],
                  json.dumps(diag))
    diag["cached"] = False
    return diag


def format_critic_block(diag: dict) -> str:
    """
    Wrap a Critic diagnosis into a prompt-ready section for the next attempt.

    Two paths:
      - replacement_block is non-empty (v2 prompt did its job) — show it
        prominently as a literal patch the optimiser is instructed to apply.
      - replacement_block is empty (v1 cache fallback, or compile error) —
        fall back to evidence-only text.

    Distinguishes "plan was wrong" (which the Planner can fix) from "code
    mis-implemented a sound plan" (which the Coder can fix).
    """
    if not diag:
        return ""
    where = "the plan itself is at fault" if diag.get("plan_was_wrong") \
        else "the plan is sound but the code mis-implemented it"
    fc = diag.get("failure_class", "other")
    ev = (diag.get("evidence") or "").strip()
    # v2 schema: prefer replacement_block; fall back to suggested_fix for
    # rows that still live in the v1 cache.
    rb = (diag.get("replacement_block")
          or diag.get("suggested_fix") or "").strip()

    lines = ["=== Critic Diagnosis ==="]
    lines.append(f"Failure class:    {fc}")
    lines.append(f"Where it broke:   {where}")
    if ev:
        lines.append(f"Evidence:         {ev}")
    if rb:
        # If the block looks like code (multi-line or contains a semicolon/
        # brace), present it as a fenced patch the optimiser should apply
        # literally; otherwise present it as a one-line suggestion.
        looks_like_code = ("\n" in rb) or any(c in rb for c in ";{}")
        if looks_like_code:
            lines.append("Apply this exact change to the previous code:")
            lines.append("```cpp")
            lines.append(rb)
            lines.append("```")
        else:
            lines.append(f"Apply this change:  {rb}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Smoke test with a stubbed critic_fn — no GPU, no compiler.
    fake_verdict = {
        "passed": False, "compiled": True, "failure_mode": "wrong_output",
        "per_test": [
            {"idx": 0, "passed": False, "input": "5",
             "expected": "120", "stdout": "24"},
        ],
    }
    def stub(_p):
        return ('{"failure_class":"off_by_one",'
                '"evidence":"loop terminates one iteration early; for n=5 we '
                'get 24 instead of 120",'
                '"replacement_block":"for (int i = 1; i <= n; i++) result *= i;",'
                '"plan_was_wrong":false}')

    d = critique("__smoke", "int main(){...}", fake_verdict,
                 prev_plan="Tier 2: rewrite factorial iteratively",
                 critic_id="__smoke_test", critic_fn=stub)
    print("diagnosis:", d)
    print()
    print(format_critic_block(d))
    # Clean up the test cache file we just wrote
    p = _cache_path("__smoke_test")
    if os.path.exists(p):
        os.remove(p)
