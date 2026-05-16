"""
PIE (Performance-Improving Edits) sample loader.

Reads pairs of (slow, fast) C++ submissions from pie-perf JSONL splits and
attaches public test cases from input.N.txt / output.N.txt files.

Each yielded sample mirrors the schema in data/bugs.py with one extension:
  source       = "pie"
  test_cases   = [{"input": str, "expected_output": str}, ...]
  problem_id   = "p03146"
  improvement_frac, cpu_time_v0, cpu_time_v1   (metadata)

The 'buggy_code' is the slow version (status_v0 = Accepted, but slower).
The 'fixed_code' is the gold faster version (status_v1 = Accepted).
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

from config import PIE_SPLIT_TEST, PIE_TESTCASES_DIR


def _load_test_cases(problem_id: str, base_dir: str = PIE_TESTCASES_DIR) -> list:
    """Read all input.N.txt / output.N.txt pairs for a problem."""
    pdir = os.path.join(base_dir, problem_id)
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


def load_pie_samples(jsonl_path: str = PIE_SPLIT_TEST,
                     n: int = 5,
                     min_improvement: float = 30.0,
                     max_lines: int = 80,
                     min_cpu_time_v0: float = 0.0,
                     skip: int = 0,
                     unique_problems: bool = True) -> list:
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
            tcs = _load_test_cases(r["problem_id"])
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
