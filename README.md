# Profile-Guided Code Correction using LLM

Research project: does providing **dynamic execution feedback** and/or **low-level profiling data** help an LLM fix C++ bugs better than reading the code alone?

Three ablation modes are compared:

- **static** — code only
- **dynamic** — code + runtime output diff (Actual vs Expected)
- **profiling** — code + runtime output diff + gprof flat profile + perf stat counters

---

## Project Structure

```
defects4c_project/
├── pipeline.py       # Main entry point — orchestrates compile → profile → LLM → verify
├── local_llm.py      # HuggingFace local model inference (repair_static / repair_dynamic)
├── llm_agent.py      # Anthropic API backend (optional alternative)
├── compiler.py       # Compiles & runs C++ code, captures stdout
├── profiler.py       # Runs gprof, formats profile summary for LLM prompt
├── config.py         # Paths, compile flags, timeouts, model defaults
├── data/
│   └── bugs.py       # Synthetic bug samples (SAMPLES list)
├── results/          # JSONL output — one file per model run
└── workspace/        # Temp binaries and gmon.out files
```

---

## Dependencies

Python packages are installed in a shared directory (already on `sys.path` via `config.py`):

| Package | Location |
|---------|----------|
| `transformers`, `bitsandbytes`, `accelerate` | `/cs/student/project_msc/2025/dsml/nmxian/py_packages/` |
| `torch` 2.5.1 | `~/.local/lib/python3.9/site-packages/` |

HuggingFace model cache: `/cs/student/project_msc/2025/dsml/nmxian/huggingface_cache/`

No installation step needed — `config.py` injects the package path automatically.

---

## Quick Start

### 1. Smoke test — single sample, one model

```bash
cd /cs/student/project_msc/2025/dsml/nmxian/defects4c_project
python3 local_llm.py
```

Runs static + dynamic repair on `001_off_by_one` using the default model
(`Qwen/Qwen2.5-Coder-7B-Instruct`) and prints pass/fail + token counts.

### 2. Run the full pipeline (all samples, all three modes)

```bash
python3 pipeline.py --backend local --mode all
```

### 3. Run a single sample by ID

```bash
python3 pipeline.py --backend local --id 001_off_by_one --mode all
```

### 4. Run only N samples

```bash
python3 pipeline.py --backend local --samples 2 --mode all
```

### 5. Run a single mode

```bash
python3 pipeline.py --backend local --mode static
python3 pipeline.py --backend local --mode dynamic
python3 pipeline.py --backend local --mode profiling
```

### 6. Use a different model

```bash
python3 pipeline.py --backend local --model deepseek-ai/deepseek-coder-6.7b-instruct
```

### 7. Run on the PIE (CodeNet) speedup benchmark

PIE samples are `(slow correct, fast correct)` C++ pairs from IBM CodeNet.
Public test cases live under `pie-perf/data/public_test_cases/<problem_id>/`
and slow/fast code is in `pie-perf/data/cpp_splits/test.jsonl`.

```bash
# 5 PIE samples, all three modes, default model
python3 pipeline.py --dataset pie --samples 5 --mode all

# Tighter filter: keep only oracle pairs with ≥ 50% improvement, ≤ 60 LOC
python3 pipeline.py --dataset pie --samples 10 \
        --pie-min-improvement 50 --pie-max-lines 60
```

Pass criterion changes for PIE: a candidate "passes" only if **all** test cases
produce correct output. Speedup vs. the slow baseline is reported per mode.

Results are saved to `results/results_pie_<model>.jsonl` (synthetic runs land
under `results/results_synthetic_<model>.jsonl`).

---

## Models Tested (≤ 16 GB VRAM)

| # | Model | HuggingFace ID | VRAM |
|---|-------|----------------|------|
| 1 | Qwen2.5-Coder-7B-Instruct ⭐ | `Qwen/Qwen2.5-Coder-7B-Instruct` | ~14 GB fp16 / ~5 GB Q4 |
| 2 | DeepSeek-Coder-6.7B-Instruct | `deepseek-ai/deepseek-coder-6.7b-instruct` | ~13 GB fp16 / ~4 GB Q4 |
| 3 | CodeLlama-13B-Instruct | `codellama/CodeLlama-13b-Instruct-hf` | ~7 GB Q4 |
| 4 | Qwen2.5-Coder-14B-Instruct | `Qwen/Qwen2.5-Coder-14B-Instruct` | ~9 GB Q4 |
| 5 | Llama-3.1-8B-Instruct | `meta-llama/Llama-3.1-8B-Instruct` | ~16 GB fp16 |

The pipeline auto-detects free VRAM: if < 15 GB free, it loads in 4-bit NF4
(`bitsandbytes`) instead of fp16. No manual flag needed.

---

## Pipeline Modes

| Mode | Synthetic dataset | PIE dataset |
|------|------------------|-------------|
| `static` | Buggy C++ source only | Slow C++ source only |
| `dynamic` | + runtime output diff (Actual vs Expected) | + per-test-case timing summary |
| `profiling` | + gprof flat profile + perf stat | + gprof flat profile + perf stat |
| `all` | Runs all three side by side | Runs all three side by side |

---

## Output

Results are saved as JSONL in `results/`, one file per (dataset, model):

```
results/results_synthetic_Qwen2.5-Coder-7B-Instruct.jsonl
results/results_pie_Qwen2.5-Coder-7B-Instruct.jsonl
```

Synthetic each line:

```json
{
  "id": "001_off_by_one",
  "bug_type": "buffer-overread",
  "static":    { "passed": true, "prompt_tokens": 312, "elapsed_s": 14.2, ... },
  "dynamic":   { "passed": true, "prompt_tokens": 389, "elapsed_s": 15.4, ... },
  "profiling": { "passed": true, "prompt_tokens": 489, "elapsed_s": 16.1, ... }
}
```

PIE each line additionally records timing and speedup:

```json
{
  "id": "pie_p00465_s878145104",
  "source": "pie",
  "problem_id": "p00465",
  "improvement_frac_oracle": 46.0,
  "baseline":  { "compiled": true, "passed": true, "mean_ms": 27.7, ... },
  "static":    { "passed": true, "mean_ms": 9.0, "speedup": 3.07, ... },
  "dynamic":   { ... },
  "profiling": { ... }
}
```

---

## Key Metrics

- **pass@1** — did the LLM's first attempt produce correct output?
- **prompt tokens** — how many tokens the static vs dynamic prompt consumed

---

## Inspecting Samples and Profiles

Two extractor scripts under `tools/` produce browseable folders of PIE
samples and profiling artefacts. Useful for sanity-checking what the LLM
sees, doing manual diff comparisons, and writing up case studies.

### Extract C++ source pairs → `pie_extracted/`

[tools/extract_pie_code.py](tools/extract_pie_code.py) pulls each
`(slow, fast)` pair out of a PIE JSONL split into individual `.cpp`
files plus a metadata sidecar.

```bash
# 30 unique-problem pairs from the test split (~30 problems × 4 files = 120 files)
python3 tools/extract_pie_code.py --limit 30 --unique-problems --out pie_extracted/

# All 5116 test pairs (heavy — ~20k files)
python3 tools/extract_pie_code.py --out pie_extracted_full/

# Specific problems we've cited in reflection.md
python3 tools/extract_pie_code.py \
    --problems p03146,p00465,p02714,p02695,p00729 \
    --out pie_extracted_cited/

# Big-improvement, short-code subset for casual browsing
python3 tools/extract_pie_code.py --limit 50 --unique-problems \
    --min-improvement 50 --max-loc 50 --out pie_extracted_short/
```

Layout per pair (one folder per problem, four files per submission):

```
pie_extracted/
├── README.md
├── p00465/
│   ├── s878145104__v0_slow.cpp     # slow correct version
│   ├── s878145104__v1_fast.cpp     # gold faster version
│   ├── s878145104__diff.txt        # textual diff between v0 and v1
│   └── s878145104__meta.json       # cpu_time, memory, improvement_frac, ...
└── p03146/...
```

Useful follow-ups:

```bash
# side-by-side diff in terminal
diff -u pie_extracted/p03146/*v0_slow.cpp pie_extracted/p03146/*v1_fast.cpp

# in VS Code: open both .cpp files, right-click first → "Compare Selected"

# read the metadata
cat pie_extracted/p03146/*meta.json
```

CLI flags:

| Flag | Effect |
|---|---|
| `--input PATH` | which JSONL split (default: `pie-perf/data/cpp_splits/test.jsonl`) |
| `--out DIR` | output directory (default `pie_extracted/`) |
| `--limit N` | cap number of pairs |
| `--problems p1,p2,...` | whitelist by `problem_id` |
| `--unique-problems` | one pair per `problem_id` |
| `--min-improvement F` | skip pairs below F% oracle improvement |
| `--max-loc N` | skip pairs whose slow code exceeds N LOC |

### Extract profiling artefacts → `pie_profiles_cited/`

[tools/extract_profile.py](tools/extract_profile.py) runs the full
profiling pipeline (compile with `-pg -g`, run on test cases, gprof,
`perf stat`, hotspot extraction, prompt formatting) and saves every
intermediate to a folder. This is exactly what the LLM sees in dynamic
and profiling modes — written to disk for inspection.

```bash
# 5 cited samples (matches our reflection.md case studies)
python3 tools/extract_profile.py \
    --problems p03146,p00465,p02714,p02695,p00729 \
    --out pie_profiles_cited/

# 10 unique-problem fast-baseline samples (cputime≥100, gprof has signal)
python3 tools/extract_profile.py --limit 10 --unique-problems \
    --min-baseline-cputime 100 --out pie_profiles/

# Slowest baselines only — strongest gprof signal
python3 tools/extract_profile.py --limit 5 --unique-problems \
    --min-baseline-cputime 500 --out pie_profiles_slow/
```

Layout per sample:

```
pie_profiles_cited/
├── README.md
├── p00465/s878145104/
│   ├── v0_slow.cpp                    # slow code (input to optimisation)
│   ├── v1_fast.cpp                    # gold fast code (oracle)
│   ├── meta.json                      # cpu_time, improvement_frac, baseline_ms_local, ...
│   ├── timing.json                    # per-test-case mean_ms / std_ms / pass
│   ├── gprof_flat.txt                 # full flat profile
│   ├── gprof_callgraph.txt            # call graph
│   ├── perf_stat.txt                  # cycles, instructions, cache-misses, branch-misses
│   ├── hotspots.json                  # parsed user-fn + top-entry hotspots used by the prompt
│   ├── annotated_source.cpp           # source after annotate_source_with_hotspots()
│   ├── prompt_runtime_feedback.txt    # exact LLM prompt block in dynamic mode
│   └── prompt_profile_summary.txt     # exact LLM prompt block in profiling mode
└── p03146/...
```

Useful follow-ups:

```bash
# what's in the gprof flat profile for every cited sample?
for d in pie_profiles_cited/*/*/; do
  echo "=== $d ==="
  head -8 "$d/gprof_flat.txt"
done

# what does the LLM actually see in profiling mode?
cat pie_profiles_cited/p00465/*/prompt_profile_summary.txt

# does the profile-mode source get hotspot annotations or the file-level fallback?
diff -u pie_profiles_cited/p00465/*/v0_slow.cpp \
        pie_profiles_cited/p00465/*/annotated_source.cpp
```

CLI flags:

| Flag | Effect |
|---|---|
| `--out DIR` | output directory (default `pie_profiles/`) |
| `--limit N` | cap number of samples (default 10) |
| `--problems p1,p2,...` | extract specific problem IDs (overrides `--limit`) |
| `--unique-problems` | one sample per `problem_id` |
| `--min-baseline-cputime MS` | drop samples with `cpu_time_v0 < MS` (default 100) |
| `--min-improvement F` | drop pairs below F% oracle improvement (default 30) |
| `--max-lines N` | drop pairs whose slow code exceeds N LOC (default 80) |

### When to use which

- Use **`extract_pie_code.py`** when you want to read or diff the source
  pairs themselves — comparing what changed between slow and fast.
- Use **`extract_profile.py`** when you want to understand *what signal
  the pipeline gives the LLM* — gprof attribution, perf counters,
  hotspot annotations, and the exact prompt blocks.

---

## Optional: Anthropic API backend

Set the API key and switch backend:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 pipeline.py --backend anthropic --samples 2
```

Model is set in `config.py` (`LLM_MODEL`, default: `claude-haiku-4-5-20251001`).
