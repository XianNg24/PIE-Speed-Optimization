#!/usr/bin/env python3
"""
Extract PIE C++ samples into individual files for easier reading.

For each (slow, fast) pair in the JSONL, writes:

    <out>/<problem_id>/<submission_id_v0>__v0_slow.cpp
    <out>/<problem_id>/<submission_id_v0>__v1_fast.cpp
    <out>/<problem_id>/<submission_id_v0>__meta.json
    <out>/<problem_id>/<submission_id_v0>__diff.txt   (only if a diff exists)

Group folder = `problem_id`, leaf prefix = `submission_id_v0` (unique per pair).

Usage:
    # everything in test split (~5k pairs)
    python3 tools/extract_pie_code.py

    # smaller slice for casual browsing
    python3 tools/extract_pie_code.py --limit 50

    # specific problems only
    python3 tools/extract_pie_code.py --problems p03146,p00465

    # different input split
    python3 tools/extract_pie_code.py \\
        --input pie-perf/data/cpp_splits/val.jsonl \\
        --out pie_extracted_val/
"""
import argparse
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="pie-perf/data/cpp_splits/test.jsonl",
                    help="PIE JSONL split to extract from")
    ap.add_argument("--out", default="pie_extracted",
                    help="Output directory")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap on number of entries to extract (default: all)")
    ap.add_argument("--problems", default=None,
                    help="Comma-separated problem_id whitelist (e.g. 'p03146,p00465')")
    ap.add_argument("--min-improvement", type=float, default=0.0,
                    help="Skip pairs with improvement_frac below this")
    ap.add_argument("--max-loc", type=int, default=None,
                    help="Skip pairs whose slow code exceeds this many LOC")
    ap.add_argument("--unique-problems", action="store_true",
                    help="Keep at most one pair per problem_id")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise SystemExit(f"Input not found: {args.input}")
    os.makedirs(args.out, exist_ok=True)

    problem_filter = None
    if args.problems:
        problem_filter = {p.strip() for p in args.problems.split(",") if p.strip()}

    n_written = 0
    n_skipped = 0
    seen_problems = set()
    used_pair_keys = set()
    counts_per_problem = {}

    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)

            pid = r.get("problem_id")
            sid_v0 = r.get("submission_id_v0", "unknown_v0")

            if problem_filter and pid not in problem_filter:
                n_skipped += 1
                continue
            if (r.get("improvement_frac") or 0) < args.min_improvement:
                n_skipped += 1
                continue
            if args.max_loc is not None and (r.get("code_v0_loc") or 0) > args.max_loc:
                n_skipped += 1
                continue
            if args.unique_problems and pid in seen_problems:
                n_skipped += 1
                continue

            pair_key = f"{pid}/{sid_v0}"
            if pair_key in used_pair_keys:
                n_skipped += 1
                continue
            used_pair_keys.add(pair_key)
            seen_problems.add(pid)

            problem_dir = os.path.join(args.out, pid)
            os.makedirs(problem_dir, exist_ok=True)

            stem = sid_v0
            slow_path = os.path.join(problem_dir, f"{stem}__v0_slow.cpp")
            fast_path = os.path.join(problem_dir, f"{stem}__v1_fast.cpp")
            meta_path = os.path.join(problem_dir, f"{stem}__meta.json")
            diff_path = os.path.join(problem_dir, f"{stem}__diff.txt")

            with open(slow_path, "w") as out:
                out.write(r.get("input", ""))
            with open(fast_path, "w") as out:
                out.write(r.get("target", ""))
            meta = {k: v for k, v in r.items()
                    if k not in {"input", "target",
                                 "code_v0_no_empty_lines", "code_v1_no_empty_lines",
                                 "diff"}}
            with open(meta_path, "w") as out:
                json.dump(meta, out, indent=2)
            diff = r.get("diff")
            if diff:
                with open(diff_path, "w") as out:
                    if isinstance(diff, list):
                        out.write("\n".join(diff))
                    else:
                        out.write(str(diff))

            n_written += 1
            counts_per_problem[pid] = counts_per_problem.get(pid, 0) + 1
            if args.limit and n_written >= args.limit:
                break

    # Top-level README
    readme = os.path.join(args.out, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w") as out:
            out.write(
                "# PIE extracted C++ samples\n\n"
                f"Extracted from `{args.input}` by `tools/extract_pie_code.py`.\n\n"
                "## Layout\n\n"
                "```\n"
                "<problem_id>/\n"
                "    <submission_id_v0>__v0_slow.cpp   # the slow but accepted version\n"
                "    <submission_id_v0>__v1_fast.cpp   # the faster accepted version\n"
                "    <submission_id_v0>__meta.json     # cpu_time, improvement_frac, ...\n"
                "    <submission_id_v0>__diff.txt      # textual diff between v0 and v1\n"
                "```\n\n"
                "## Quick browsing tips\n\n"
                "- `diff <problem_id>/*v0_slow.cpp <problem_id>/*v1_fast.cpp` for a side-by-side\n"
                "- `cat <problem_id>/*meta.json` shows the speedup metadata\n"
                "- VS Code's compare-files ('Compare Selected') works directly on the .cpp pair\n"
            )

    print(f"Wrote {n_written} pairs across {len(counts_per_problem)} problems "
          f"to {args.out}/")
    if n_skipped:
        print(f"Skipped {n_skipped} entries (filters)")
    if counts_per_problem:
        top = sorted(counts_per_problem.items(), key=lambda kv: -kv[1])[:10]
        print("Pairs per problem (top 10):")
        for pid, n in top:
            print(f"  {pid:<12} {n}")


if __name__ == "__main__":
    main()
