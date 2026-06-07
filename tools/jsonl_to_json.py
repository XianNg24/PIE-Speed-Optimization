#!/usr/bin/env python3
"""
Convert a JSONL file (one JSON object per line) into a pretty-printed JSON
array that editors can fold and humans can read.

Why both formats exist:
  - results.jsonl is APPEND-SAFE — the pipeline writes one line per sample as
    it completes, so a crashed run keeps its partial results.
  - results.json is a single indented array — easy to open, fold, and diff,
    but cannot be appended to incrementally.

Usage:
    # one file -> sibling .json
    python3 tools/jsonl_to_json.py results/run_20260520-130522/results.jsonl

    # explicit output path
    python3 tools/jsonl_to_json.py path/in.jsonl -o path/out.json

    # every run dir's results.jsonl at once
    python3 tools/jsonl_to_json.py --all
"""
import argparse
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)


def convert(in_path: str, out_path: str = None, indent: int = 2) -> tuple:
    """Read a .jsonl, write a pretty .json array. Returns (out_path, n_rows)."""
    with open(in_path) as f:
        objs = [json.loads(line) for line in f if line.strip()]
    if out_path is None:
        out_path = os.path.splitext(in_path)[0] + ".json"
    with open(out_path, "w") as f:
        json.dump(objs, f, indent=indent, default=str)
    return out_path, len(objs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl_path", nargs="?",
                    help="Input .jsonl file (omit when using --all)")
    ap.add_argument("-o", "--out", default=None,
                    help="Output .json path (default: sibling .json)")
    ap.add_argument("--indent", type=int, default=2)
    ap.add_argument("--all", action="store_true",
                    help="Convert every results/run_*/results.jsonl")
    args = ap.parse_args()

    if args.all:
        paths = sorted(glob.glob(os.path.join(_PROJECT, "results", "run_*",
                                              "results.jsonl")))
        # also include the global ledgers
        paths += sorted(glob.glob(os.path.join(_PROJECT, "results",
                                              "results_*.jsonl")))
        if not paths:
            print("No results*.jsonl files found.")
            return
        for p in paths:
            out, n = convert(p, indent=args.indent)
            print(f"  {p}  ->  {out}  ({n} rows)")
        return

    if not args.jsonl_path:
        ap.error("provide a jsonl_path or use --all")
    out, n = convert(args.jsonl_path, args.out, args.indent)
    print(f"Wrote {out}  ({n} rows)")


if __name__ == "__main__":
    main()
