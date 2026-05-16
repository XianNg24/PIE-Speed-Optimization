#!/usr/bin/env python3
"""
Extract profiling artefacts (gprof + perf) for PIE samples into a folder
that's easy to browse.

For each sample, writes:

    <out>/<problem_id>/<submission_id_v0>/
        v0_slow.cpp                    # the slow code that was profiled
        v1_fast.cpp                    # the gold fast code, for comparison
        meta.json                      # cpu_time, improvement_frac, baseline_ms ...

        gprof_flat.txt                 # gprof flat profile (raw)
        gprof_callgraph.txt            # gprof call graph (raw)
        perf_stat.txt                  # perf stat output
        timing.json                    # per-test-case mean_ms / std / pass

        # Exactly what our pipeline feeds the LLM in each mode:
        prompt_runtime_feedback.txt    # dynamic-mode feedback block
        prompt_profile_summary.txt     # profiling-mode feedback block
        annotated_source.cpp           # source after annotate_source_with_hotspots()
        hotspots.json                  # parsed user-function + top-entry hotspots

Usage:
    # 10 unique-problem samples with cputime>=100 (interesting profiles)
    python3 tools/extract_profile.py --limit 10 --unique-problems \\
        --min-baseline-cputime 100

    # specific problems
    python3 tools/extract_profile.py --problems p03146,p00465,p02714 \\
        --out pie_profiles_cited/
"""
import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

from data.pie_loader import load_pie_samples
from compiler import compile_and_run_tests
from profiler import (
    profile, format_pie_runtime_feedback, format_pie_profile_for_llm,
    parse_gprof_hotspots, annotate_source_with_hotspots, parse_gprof_top_entries,
)


def _gprof_full(binary_path, gmon_path):
    """Run gprof without -b for full flat + call-graph output."""
    try:
        proc = subprocess.run(
            ["gprof", binary_path, gmon_path],
            capture_output=True, text=True, timeout=30,
        )
        return proc.stdout if proc.returncode == 0 else proc.stderr
    except Exception as e:
        return f"gprof exception: {e}"


def _split_flat_and_callgraph(gprof_out):
    """Naively split gprof's stdout into flat profile and call graph sections."""
    lines = gprof_out.split("\n")
    sections = {"flat": [], "callgraph": []}
    cur = None
    for line in lines:
        if "Flat profile" in line:
            cur = "flat"
        elif "Call graph" in line:
            cur = "callgraph"
        if cur:
            sections[cur].append(line)
    return ("\n".join(sections["flat"]), "\n".join(sections["callgraph"]))


def extract_one(sample, out_dir, verbose=True):
    pid = sample["problem_id"]
    sid = sample["id"].replace(f"pie_{pid}_", "")     # e.g. s047505757
    target = os.path.join(out_dir, pid, sid)
    os.makedirs(target, exist_ok=True)

    if verbose:
        print(f"[{pid}/{sid}] compiling and timing slow code "
              f"(v0 cpu_time={sample['cpu_time_v0']}ms)...")

    # 1. Source files for visual diff
    with open(os.path.join(target, "v0_slow.cpp"), "w") as f:
        f.write(sample["buggy_code"])
    with open(os.path.join(target, "v1_fast.cpp"), "w") as f:
        f.write(sample["fixed_code"])

    # 2. Compile + time the slow code on every test case
    slow = compile_and_run_tests(
        sample["buggy_code"], name=f"profile_extract_{pid}_{sid}",
        test_cases=sample["test_cases"],
    )
    timing_summary = {
        "compiled": slow["compiled"],
        "passed": slow["passed"],
        "mean_ms": slow["mean_ms"],
        "median_ms": slow["median_ms"],
        "per_test": slow.get("per_test", []),
    }
    with open(os.path.join(target, "timing.json"), "w") as f:
        json.dump(timing_summary, f, indent=2)

    if not slow["compiled"] or not slow.get("binary_path"):
        with open(os.path.join(target, "ERROR.txt"), "w") as f:
            f.write("Slow code failed to compile:\n")
            f.write(slow.get("compile_error", "")[:2000])
        if verbose:
            print(f"  -> compile failed; wrote ERROR.txt")
        return False

    # 3. Pick the slowest test case as the profiling input
    per = slow.get("per_test", [])
    ok_tests = [i for i, t in enumerate(per)
                if not t.get("timed_out") and t.get("mean_ms") is not None]
    profile_idx = (max(ok_tests, key=lambda i: per[i]["mean_ms"]) if ok_tests else 0)
    stdin_for_profile = sample["test_cases"][profile_idx]["input"]

    # 4. Profile
    raw = profile(slow["binary_path"], stdin_data=stdin_for_profile)
    gprof_str = raw.get("gprof", "")
    perf_str  = raw.get("perf_stat", "")

    # 5. Also run gprof without -b to capture the full call graph
    work_dir = os.path.dirname(slow["binary_path"])
    gmon_files = sorted([f for f in os.listdir(work_dir) if f.startswith("gmon")])
    full_gprof = ""
    if gmon_files:
        full_gprof = _gprof_full(slow["binary_path"],
                                  os.path.join(work_dir, gmon_files[0]))
    flat_section, callgraph_section = _split_flat_and_callgraph(full_gprof)

    # Fall back to the truncated flat profile from profile() if full one is empty
    if not flat_section.strip():
        flat_section = gprof_str

    with open(os.path.join(target, "gprof_flat.txt"), "w") as f:
        f.write(flat_section)
    with open(os.path.join(target, "gprof_callgraph.txt"), "w") as f:
        f.write(callgraph_section if callgraph_section.strip() else "(no call graph)")
    with open(os.path.join(target, "perf_stat.txt"), "w") as f:
        f.write(perf_str)

    # 6. Hotspot extraction (the structured form the pipeline produces)
    user_hotspots = parse_gprof_hotspots(gprof_str)
    top_entries   = parse_gprof_top_entries(gprof_str)
    with open(os.path.join(target, "hotspots.json"), "w") as f:
        json.dump({
            "profiled_test_idx": profile_idx,
            "profiled_test_mean_ms": per[profile_idx].get("mean_ms") if per else None,
            "user_function_hotspots": user_hotspots,
            "top_gprof_entries": top_entries,
        }, f, indent=2)

    # 7. Annotated source — what profile-mode prompt actually sees
    annotated = annotate_source_with_hotspots(
        sample["buggy_code"], user_hotspots, gprof_output=gprof_str,
    )
    with open(os.path.join(target, "annotated_source.cpp"), "w") as f:
        f.write(annotated)

    # 8. The exact LLM prompt blocks
    runtime_fb = format_pie_runtime_feedback(per, slow["mean_ms"])
    profile_summary = format_pie_profile_for_llm(raw, per, slow["mean_ms"])
    with open(os.path.join(target, "prompt_runtime_feedback.txt"), "w") as f:
        f.write(runtime_fb)
    with open(os.path.join(target, "prompt_profile_summary.txt"), "w") as f:
        f.write(profile_summary)

    # 9. Metadata
    meta = {
        "problem_id": pid,
        "submission_id_v0": sid,
        "cpu_time_v0_ms_oracle": sample["cpu_time_v0"],
        "cpu_time_v1_ms_oracle": sample["cpu_time_v1"],
        "improvement_frac_oracle": sample["improvement_frac"],
        "n_test_cases": len(sample["test_cases"]),
        "baseline_mean_ms_local": slow["mean_ms"],
        "baseline_median_ms_local": slow["median_ms"],
        "baseline_passed_local": slow["passed"],
        "profiled_test_idx": profile_idx,
        "n_user_function_hotspots": len(user_hotspots),
        "n_top_gprof_entries": len(top_entries),
    }
    with open(os.path.join(target, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    if verbose:
        ufh = ", ".join(h["name"] for h in user_hotspots[:3]) or "(none)"
        print(f"  -> baseline mean={slow['mean_ms']}ms, "
              f"user_hotspots=[{ufh}], top_gprof_entries={len(top_entries)}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="pie_profiles", help="Output directory")
    ap.add_argument("--limit", type=int, default=10,
                    help="How many samples to extract (default 10)")
    ap.add_argument("--problems", default=None,
                    help="Comma-separated problem_id list (overrides --limit)")
    ap.add_argument("--unique-problems", action="store_true",
                    help="One sample per problem_id")
    ap.add_argument("--min-improvement", type=float, default=30.0)
    ap.add_argument("--max-lines", type=int, default=80)
    ap.add_argument("--min-baseline-cputime", type=float, default=100.0,
                    help="Skip pairs with cpu_time_v0 below this (ms-ish). "
                         "Higher = more meaningful gprof attribution.")
    args = ap.parse_args()

    if args.problems:
        wanted = {p.strip() for p in args.problems.split(",") if p.strip()}
        # Load broadly then filter
        candidates = load_pie_samples(
            n=10000,
            min_improvement=args.min_improvement,
            max_lines=args.max_lines,
            min_cpu_time_v0=0.0,    # don't pre-filter cputime when problems are explicit
            unique_problems=False,
        )
        samples = [s for s in candidates if s["problem_id"] in wanted]
        # keep at most one sample per requested problem
        seen = set()
        deduped = []
        for s in samples:
            if s["problem_id"] in seen: continue
            seen.add(s["problem_id"])
            deduped.append(s)
        samples = deduped
        if not samples:
            raise SystemExit(f"No PIE samples matched problems={wanted}")
    else:
        samples = load_pie_samples(
            n=args.limit,
            min_improvement=args.min_improvement,
            max_lines=args.max_lines,
            min_cpu_time_v0=args.min_baseline_cputime,
            unique_problems=args.unique_problems,
        )

    os.makedirs(args.out, exist_ok=True)
    n_ok = n_fail = 0
    for s in samples:
        try:
            ok = extract_one(s, args.out)
        except Exception as e:
            print(f"[{s['id']}] FAILED: {e}")
            ok = False
        n_ok += int(ok)
        n_fail += int(not ok)

    # Top-level README
    readme = os.path.join(args.out, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w") as f:
            f.write(
                "# PIE profiling artefacts\n\n"
                "Each sub-folder contains everything the pipeline computes for "
                "one PIE sample, written as plain files for easy reading.\n\n"
                "## Layout\n\n"
                "```\n"
                "<problem_id>/<submission_id>/\n"
                "    v0_slow.cpp                    # slow code (input to optimisation)\n"
                "    v1_fast.cpp                    # gold fast code (oracle)\n"
                "    meta.json                      # cpu_time, improvement_frac, ...\n"
                "    timing.json                    # per-test mean_ms / std\n"
                "    gprof_flat.txt                 # flat profile (full)\n"
                "    gprof_callgraph.txt            # call graph\n"
                "    perf_stat.txt                  # cycles, instructions, cache, branch\n"
                "    hotspots.json                  # parsed hotspots used by the prompt\n"
                "    annotated_source.cpp           # source seen by profiling mode\n"
                "    prompt_runtime_feedback.txt    # dynamic-mode prompt block\n"
                "    prompt_profile_summary.txt     # profiling-mode prompt block\n"
                "```\n"
            )
    print(f"\nDone. {n_ok} ok, {n_fail} failed. Out: {args.out}/")


if __name__ == "__main__":
    main()
