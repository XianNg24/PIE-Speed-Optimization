#!/usr/bin/env python3
"""
Backfill `*.diff` files into existing `run_<timestamp>/` directories that
predate the diff-generating pipeline change.

For each `samples/<id>/` folder found, writes:

    oracle_v0_to_v1.diff                       # v0 -> v1 (gold reference)
    <mode>/candidate_<i>_vs_v0.diff            # each candidate vs original
    <mode>/winner_vs_v0.diff                   # winner vs original

All diffs are normalised via `tools/normalize_cpp.normalize_cpp` first.

Existing files are overwritten. Idempotent — safe to re-run.

Usage:
    python3 tools/backfill_diffs.py results/run_20260515-184011
    python3 tools/backfill_diffs.py results/run_*                  # multiple
    python3 tools/backfill_diffs.py --all                          # every run dir
"""
import argparse
import difflib
import glob
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from normalize_cpp import normalize_cpp


def _make_diff(a, b, fromfile, tofile, n_context=3):
    a, b = normalize_cpp(a), normalize_cpp(b)
    a_lines = [l if l.endswith("\n") else l + "\n" for l in a.splitlines(keepends=True)]
    b_lines = [l if l.endswith("\n") else l + "\n" for l in b.splitlines(keepends=True)]
    return "".join(difflib.unified_diff(
        a_lines, b_lines, fromfile=fromfile, tofile=tofile, n=n_context,
    ))


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content if content else "(no diff — files are identical)\n")


def backfill_sample(sample_dir, verbose=True):
    # Find v0 and v1 (PIE: v0_slow.cpp / v1_fast.cpp; synthetic: v0_buggy / v1_fixed)
    v0_path = v1_path = v0_name = v1_name = None
    for name in ("v0_slow.cpp", "v0_buggy.cpp"):
        p = os.path.join(sample_dir, name)
        if os.path.exists(p):
            v0_path, v0_name = p, name
            break
    for name in ("v1_fast.cpp", "v1_fixed.cpp"):
        p = os.path.join(sample_dir, name)
        if os.path.exists(p):
            v1_path, v1_name = p, name
            break
    if not v0_path:
        if verbose:
            print(f"  [{os.path.basename(sample_dir)}] no v0_*.cpp — skipping")
        return 0
    v0_src = open(v0_path).read()
    v1_src = open(v1_path).read() if v1_path else None

    n_written = 0

    # Oracle diff
    if v1_src is not None:
        oracle_path = os.path.join(sample_dir, "oracle_v0_to_v1.diff")
        _write(oracle_path, _make_diff(v0_src, v1_src,
                                        fromfile=v0_name, tofile=v1_name))
        n_written += 1

    # Per-mode candidates
    for mode in ("static", "dynamic", "profiling"):
        mode_dir = os.path.join(sample_dir, mode)
        if not os.path.isdir(mode_dir):
            continue
        for fname in sorted(os.listdir(mode_dir)):
            if fname.startswith("candidate_") and fname.endswith(".cpp"):
                idx_str = fname[len("candidate_"):-len(".cpp")]
                cand_src = open(os.path.join(mode_dir, fname)).read()
                _write(os.path.join(mode_dir, f"candidate_{idx_str}_vs_v0.diff"),
                       _make_diff(v0_src, cand_src,
                                  fromfile=v0_name,
                                  tofile=f"{mode}/{fname}"))
                n_written += 1
            elif fname == "winner.cpp":
                cand_src = open(os.path.join(mode_dir, fname)).read()
                _write(os.path.join(mode_dir, "winner_vs_v0.diff"),
                       _make_diff(v0_src, cand_src,
                                  fromfile=v0_name,
                                  tofile=f"{mode}/winner.cpp"))
                n_written += 1
    if verbose:
        print(f"  [{os.path.basename(sample_dir)}] wrote {n_written} diff(s)")
    return n_written


def backfill_run(run_dir, verbose=True):
    samples_dir = os.path.join(run_dir, "samples")
    if not os.path.isdir(samples_dir):
        if verbose:
            print(f"[{run_dir}] no samples/ subdir — skipping")
        return 0
    n_total = 0
    n_samples = 0
    for sample_id in sorted(os.listdir(samples_dir)):
        sd = os.path.join(samples_dir, sample_id)
        if not os.path.isdir(sd):
            continue
        n_total += backfill_sample(sd, verbose=verbose)
        n_samples += 1
    if verbose:
        print(f"[{run_dir}] {n_samples} samples, {n_total} diff files written")
    return n_total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="*",
                    help="run_<timestamp>/ directories to backfill")
    ap.add_argument("--all", action="store_true",
                    help="Backfill every results/run_* directory")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.all:
        run_dirs = sorted(glob.glob(os.path.join(_PROJECT, "results", "run_*")))
    else:
        run_dirs = args.run_dirs
    if not run_dirs:
        ap.error("provide run dirs or --all")

    total = 0
    for rd in run_dirs:
        total += backfill_run(rd, verbose=not args.quiet)
    print(f"\nTotal: {total} diff files across {len(run_dirs)} run dirs")


if __name__ == "__main__":
    main()
