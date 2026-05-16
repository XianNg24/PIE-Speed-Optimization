"""
Quick demo / integration test that runs without an ANTHROPIC_API_KEY.
Verifies:
  1. All 5 bug samples compile
  2. Buggy code produces wrong output
  3. Fixed code produces correct output
  4. Profiling pipeline runs end-to-end on each sample

Run:
    python demo.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from data.bugs import SAMPLES
from compiler import compile_and_run
from profiler import profile, format_profile_for_llm

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(cond, label):
    status = PASS if cond else FAIL
    print(f"  [{status}] {label}")
    return cond


def main():
    all_ok = True
    print("=" * 60)
    print("Profile-Guided Code Correction — Demo / Integration Test")
    print("=" * 60)

    for s in SAMPLES:
        print(f"\nSample: {s['id']}  [{s['bug_type']}]")
        print(f"  {s['description']}")

        # 1. Buggy code compiles
        rb = compile_and_run(
            s["buggy_code"], name=f"demo_{s['id']}_buggy",
            expected_output=s["expected_output"]
        )
        ok = check(rb["compiled"], "Buggy code compiles")
        all_ok = all_ok and ok

        # 2. Buggy code produces wrong output
        ok = check(not rb["passed"], "Buggy code produces WRONG output (expected)")
        all_ok = all_ok and ok
        print(f"     stdout={repr(rb['stdout'].strip())}  expected={repr(s['expected_output'].strip())}")

        # 3. Fixed code compiles and passes
        rf = compile_and_run(
            s["fixed_code"], name=f"demo_{s['id']}_fixed",
            expected_output=s["expected_output"]
        )
        ok = check(rf["compiled"] and rf["passed"], "Fixed code compiles and passes")
        all_ok = all_ok and ok

        # 4. Profiling runs on the buggy binary
        if rb["compiled"] and rb.get("binary_path"):
            raw = profile(rb["binary_path"])
            summary = format_profile_for_llm(
                raw, rb.get("compile_error", ""),
                actual_output=rb["stdout"],
                expected_output=s["expected_output"]
            )
            has_gprof = "Flat profile" in summary or "gprof" in summary
            has_perf  = "perf" in summary.lower()
            ok = check(has_gprof or has_perf, "Profiling output captured")
            all_ok = all_ok and ok
            print(f"     Profile snippet: {summary[summary.find(chr(10))+1:summary.find(chr(10))+1+80].strip()!r}")

    print(f"\n{'='*60}")
    if all_ok:
        print(f"[{PASS}] All checks passed. Pipeline is ready.")
        print("\nNext step: set ANTHROPIC_API_KEY and run:")
        print("  python pipeline.py --samples 2 --mode both")
    else:
        print(f"[{FAIL}] Some checks failed — see above.")
    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
