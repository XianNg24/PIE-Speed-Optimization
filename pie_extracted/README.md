# PIE extracted C++ samples

Extracted from `pie-perf/data/cpp_splits/test.jsonl` by `tools/extract_pie_code.py`.

## Layout

```
<problem_id>/
    <submission_id_v0>__v0_slow.cpp   # the slow but accepted version
    <submission_id_v0>__v1_fast.cpp   # the faster accepted version
    <submission_id_v0>__meta.json     # cpu_time, improvement_frac, ...
    <submission_id_v0>__diff.txt      # textual diff between v0 and v1
```

## Quick browsing tips

- `diff <problem_id>/*v0_slow.cpp <problem_id>/*v1_fast.cpp` for a side-by-side
- `cat <problem_id>/*meta.json` shows the speedup metadata
- VS Code's compare-files ('Compare Selected') works directly on the .cpp pair
