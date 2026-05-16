#!/usr/bin/env python3
"""
Split an append-only results/*.jsonl into per-run files based on run_id.

Each output file is named:
    <stem>__<run_id>__<dataset>__n<N>__k<K>__cputime<MIN>.jsonl

Rows without a run_id (older runs) are written to <stem>__legacy.jsonl.

Usage:
    python3 tools/split_results.py results/results_pie_Qwen2.5-Coder-7B-Instruct.jsonl
"""
import argparse
import collections
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl_path")
    ap.add_argument("--out-dir", default=None,
                    help="Output directory (default: <input>_split/)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.jsonl_path):
        print(f"No such file: {args.jsonl_path}", file=sys.stderr)
        sys.exit(1)

    base, _ = os.path.splitext(args.jsonl_path)
    out_dir = args.out_dir or (base + "_split")
    if not args.dry_run:
        os.makedirs(out_dir, exist_ok=True)

    by_run = collections.defaultdict(list)
    legacy = []
    for line in open(args.jsonl_path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        rid = r.get("run_id")
        (by_run[rid] if rid else legacy).append(r)

    stem = os.path.basename(base)
    written = []

    for rid, rows in sorted(by_run.items()):
        meta = rows[0].get("run_meta", {}) or {}
        dataset = meta.get("dataset", "?")
        k = meta.get("k", 1)
        cputime = meta.get("pie_min_baseline_cputime", 0.0)
        n = len(rows)
        fname = (f"{stem}__{rid}__{dataset}__n{n}__k{k}"
                 f"__cputime{int(cputime)}.jsonl")
        path = os.path.join(out_dir, fname)
        if not args.dry_run:
            with open(path, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        written.append((path, n, meta))

    if legacy:
        path = os.path.join(out_dir, f"{stem}__legacy.jsonl")
        if not args.dry_run:
            with open(path, "w") as f:
                for r in legacy:
                    f.write(json.dumps(r) + "\n")
        written.append((path, len(legacy), {"note": "untagged rows"}))

    print(f"{'WOULD WRITE' if args.dry_run else 'wrote'} {len(written)} files to {out_dir}/")
    for path, n, meta in written:
        info = (f"k={meta.get('k',1)} cputime>={meta.get('pie_min_baseline_cputime','?')}"
                if meta.get("k") is not None else meta.get("note", ""))
        print(f"  {os.path.basename(path):<90} n={n:<4}  {info}")


if __name__ == "__main__":
    main()
