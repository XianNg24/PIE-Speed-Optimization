#!/usr/bin/env python3
"""
Regenerate `summary.txt` (and the oracle column) for existing
`results/run_<timestamp>/` directories that pre-date the change.

Reads `results.jsonl` + `meta.json`, prints the same table the pipeline
would have printed at run-end, writes it to `summary.txt`.

Usage:
    python3 tools/backfill_summary_txt.py results/run_20260518-173810
    python3 tools/backfill_summary_txt.py --all
"""
import argparse
import glob
import json
import os
import statistics
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)


def _oracle_str(impr):
    if impr is None: return "—"
    if impr >= 99.5: return ">99x"
    if impr <= 0:    return "1.00x"
    return f"{100.0/(100.0-impr):.2f}x"


def _quantile(xs, q):
    if not xs: return None
    xs = sorted(xs); k = (len(xs)-1)*q
    lo, hi = int(k), min(int(k)+1, len(xs)-1)
    return xs[lo] + (xs[hi]-xs[lo])*(k-int(k))


def backfill(run_dir, verbose=True):
    meta_p = os.path.join(run_dir, "meta.json")
    rj_p   = os.path.join(run_dir, "results.jsonl")
    if not (os.path.exists(meta_p) and os.path.exists(rj_p)):
        if verbose: print(f"[{run_dir}] missing meta.json or results.jsonl — skip")
        return False
    meta = json.load(open(meta_p))
    rows = [json.loads(l) for l in open(rj_p) if l.strip()]
    modes = meta.get("modes", ["static","dynamic","profiling"])
    k = meta.get("k", 1)
    metric_label = f"pass@{k}" if k > 1 else "pass@1"
    dataset = meta.get("dataset", "pie")
    run_id = meta.get("run_id", os.path.basename(run_dir).replace("run_",""))

    lines = []
    def s(line=""): lines.append(line)
    s("="*70)
    s(f"SUMMARY  ({dataset}, {len(rows)} samples, "
      f"modes={','.join(modes)}, {metric_label})")
    s("="*70)

    if dataset == "pie":
        mode_col_w, oracle_col_w = 22, 10
        header = (f"{'ID':<32}{'oracle':>{oracle_col_w}}"
                  + "".join(f"{m:>{mode_col_w}}" for m in modes))
        s(header)
        s("-"*len(header))
        for r in rows:
            o = _oracle_str(r.get("improvement_frac_oracle"))
            cells = []
            for m in modes:
                e = r.get(m)
                if e is None: cells.append("—")
                elif e["passed"]:
                    sp = f"{e['speedup']:.2f}x" if e.get("speedup") is not None else "?"
                    cells.append(f"PASS {sp}")
                else:
                    fm = e.get("failure_mode") or ("compile" if not e["compiled"] else "?")
                    tag = "ERR" if fm == "compile" else "FAIL"
                    cells.append(f"{tag} ({fm})")
            s(f"{r['id']:<32}{o:>{oracle_col_w}}" + "".join(f"{c:>{mode_col_w}}" for c in cells))
        s()

        # Oracle aggregate
        osps = [100.0/(100.0-r["improvement_frac_oracle"])
                for r in rows if r.get("improvement_frac_oracle") is not None
                and 0 < r["improvement_frac_oracle"] < 99.5]
        if osps:
            def fx(x): return f"{x:.2f}x" if x is not None else "—"
            s(f"{'Oracle':<10} (reference): "
              f"mean={fx(statistics.mean(osps))} "
              f"median={fx(statistics.median(osps))} "
              f"max={fx(max(osps))}   "
              f"(speedup the gold v1 achieves vs v0, per PIE metadata)")

        n = len(rows)
        for m in modes:
            ents = [r.get(m) for r in rows if r.get(m)]
            passed = sum(1 for e in ents if e["passed"])
            sps = [e["speedup"] for e in ents
                   if e["passed"] and e.get("speedup") is not None]
            faster = sum(1 for x in sps if x > 1.0)
            fcounts = {}
            for e in ents:
                if not e["passed"]:
                    fm = e.get("failure_mode") or ("compile" if not e["compiled"] else "unknown")
                    fcounts[fm] = fcounts.get(fm, 0) + 1
            fs = ", ".join(f"{k}={v}" for k,v in sorted(fcounts.items())) or "—"
            def fx(x): return f"{x:.2f}x" if x is not None else "—"
            s(f"{m.capitalize():<10} {metric_label}: {passed}/{n} = {passed/n*100:.0f}%   "
              f"faster: {faster}/{n}   "
              f"speedup mean={fx(statistics.mean(sps) if sps else None)} "
              f"median={fx(statistics.median(sps) if sps else None)} "
              f"p25={fx(_quantile(sps,0.25))} p75={fx(_quantile(sps,0.75))} "
              f"max={fx(max(sps) if sps else None)}   "
              f"failures: [{fs}]")
    else:
        # synthetic
        header = f"{'ID':<30}" + "".join(f"{m:>10}" for m in modes)
        s(header); s("-"*len(header))
        def _st(e):
            if not e: return "  -"
            if e["passed"]: return "PASS"
            return "FAIL" if e["compiled"] else "ERR"
        for r in rows:
            s(f"{r['id']:<30}" + "".join(f"{_st(r.get(m)):>10}" for m in modes))
        s()
        n = len(rows)
        for m in modes:
            passed = sum(1 for r in rows if r.get(m) and r[m]["passed"])
            s(f"{m.capitalize():<10} {metric_label}: {passed}/{n} = {passed/n*100:.0f}%")

    out = os.path.join(run_dir, "summary.txt")
    with open(out, "w") as f: f.write("\n".join(lines) + "\n")
    if verbose: print(f"[{os.path.basename(run_dir)}] wrote summary.txt ({len(lines)} lines)")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    targets = (sorted(glob.glob(os.path.join(_PROJECT, "results", "run_*")))
               if args.all else args.run_dirs)
    if not targets:
        ap.error("provide run_dirs or --all")
    n = sum(int(backfill(rd)) for rd in targets)
    print(f"\n{n} summary.txt files written")


if __name__ == "__main__":
    main()
