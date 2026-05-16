# PIE profiling artefacts

Each sub-folder contains everything the pipeline computes for one PIE sample, written as plain files for easy reading.

## Layout

```
<problem_id>/<submission_id>/
    v0_slow.cpp                    # slow code (input to optimisation)
    v1_fast.cpp                    # gold fast code (oracle)
    meta.json                      # cpu_time, improvement_frac, ...
    timing.json                    # per-test mean_ms / std
    gprof_flat.txt                 # flat profile (full)
    gprof_callgraph.txt            # call graph
    perf_stat.txt                  # cycles, instructions, cache, branch
    hotspots.json                  # parsed hotspots used by the prompt
    annotated_source.cpp           # source seen by profiling mode
    prompt_runtime_feedback.txt    # dynamic-mode prompt block
    prompt_profile_summary.txt     # profiling-mode prompt block
```
