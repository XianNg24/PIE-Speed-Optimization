# Profile-Guided Code Correction & Optimisation with LLMs

Research pipeline that asks **does richer feedback help an LLM optimise C++?**
Three ablation modes are compared on the [PIE / IBM CodeNet](https://pie4perf.com)
performance-improving-edits dataset:

| Mode | What the LLM sees |
|---|---|
| `static` | the slow C++ source only |
| `dynamic` | + runtime feedback (output diff, per-test timings) |
| `profiling` | + gprof flat profile, `perf stat` counters, gcov hot lines |

On top of the base ablation, the pipeline can layer:
- **Pass@k sampling** with self-repair retry on failure
- **Iterate-on-speedup**: ask for a strictly faster version after a pass
- **LLM-side problem classifier** (problem-statement → tag, JIT-cached on disk)
- **LLM-side complexity predictor** (source → Big-O class, JIT-cached on disk)
- **Reasoning agent** (three-tier optimisation plan injected into the optimiser prompt)
- **Critic agent** (failure diagnoses + literal C++ patches; delta-debug input shrinker as a tool)

See [`architecture.md`](architecture.md) for the full agentic design.

---

## 1. Setup

### 1.1 Clone the repo

```bash
git clone https://github.com/XianNg24/PIE-SPEED-OPTIMIZATION
cd PIE-SPEED-OPTIMIZATION
```

### 1.2 System tools

The pipeline needs C++ build tools and Linux profilers:

```bash
# Debian / Ubuntu — gcov ships with g++ (no separate package).
sudo apt install g++ binutils linux-tools-generic clang-format

# RHEL / Rocky / Fedora
sudo dnf install gcc-c++ binutils perf gcc clang-tools-extra
```

On AWS EC2 the `linux-tools-generic` perf binary may not match the
AWS-flavoured kernel. If `perf --version` complains, install the matching
variant:

```bash
sudo apt install linux-tools-aws "linux-tools-$(uname -r)"
```

Verify everything is on PATH:
Y
```bash
g++ --version | head -1 \
  && gcov --version | head -1 \
  && gprof --version | head -1 \
  && perf --version
```

`perf` is optional — without it, `--mode profiling` skips the `perf stat`
block but keeps gprof + gcov.

### 1.3 Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The default backend uses HuggingFace `transformers` locally (GPU recommended:
a single 24 GB card handles all listed 7B models). For the Anthropic backend
only the `anthropic` SDK is needed.

If you are on a managed cluster where heavy deps (torch, transformers,
bitsandbytes) live in a shared partition outside your home quota, point
`config.py` at it via:

```bash
export PROJECT_PKG_DIR=/path/to/shared/py_packages
```

The variable is opt-in — unset, `config.py` simply ignores it and your
virtualenv supplies the packages as usual.

### 1.4 PIE / CodeNet dataset

The PIE dataset is a separate repo. Clone it under the project root as
`pie-perf/`:

```bash
git clone https://github.com/madaan/pie-perf.git
```

The clone gives you `public_test_cases/`, the English-translated CodeNet
problem statements (`problem_statements_translated.zip`), `knn_prompts/`,
and `sample/`. The actual **C++ training/eval splits**
(`cpp_splits/{train,val,test}.jsonl`) are hosted on Google Drive as a
separate ~100 MB archive — without these the loader can't find any samples.
Download them with `gdown`:

```bash
pip install gdown    # if not already installed
cd pie-perf/data
gdown 1NqMT7kqCwk99hj4BjpUcsxLIzPFv_DtT -O cpp_splits.zip
unzip cpp_splits.zip && rm cpp_splits.zip
cd ../..
ls pie-perf/data/cpp_splits/    # expect: train.jsonl, val.jsonl, test.jsonl, test-1k.jsonl
```

### 1.5 Merged test cases (optional, recommended)

PIE's public test cases are 2-4 per problem on average — too narrow for
reliable correctness validation (the pipeline reports several cases where a
candidate passes the 2 visible tests but is algorithmically wrong on the
hidden ones). The PIE authors also distribute a `merged_testcases.tar.gz`
archive with ~100 tests per problem (≈ 178 k cases across 2 013 problems).
Grab it from the [PIE website](https://pie4perf.com) or the dataset link in
`pie-perf/README.md`, then:

```bash
mv merged_testcases.tar.gz pie-perf/
cd pie-perf && tar -xzf merged_testcases.tar.gz -C data/
```

You should see `pie-perf/data/merged_test_cases/<problem_id>/input.N.txt`
etc. The pipeline automatically prefers `merged_test_cases/` when it exists
and falls back to `public_test_cases/` for problems not in the merged set.

Disk cost: ~700 MB extracted. Eval cost grows roughly linearly with test
count — use `--pie-max-tests N` to cap.

### 1.6 HuggingFace cache (for big models)

By default model weights download to `~/.cache/huggingface`. Override via:

```bash
export HF_HOME=/path/with/space
export TRANSFORMERS_CACHE=$HF_HOME/hub
```

For gated models (CodeLlama, Llama-3, etc.) set `HF_TOKEN` after accepting
the licence on the HuggingFace model page.

### 1.7 Anthropic backend (optional)

Only needed if you want `--backend anthropic`:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## 2. Quick start

```bash
# 5 PIE samples, all three modes, default model (Qwen2.5-Coder-7B-Instruct)
python3 pipeline.py --dataset pie --samples 5

# Same, with sampling (k=4) and 2 self-repair rounds
python3 pipeline.py --dataset pie --samples 5 --k 4 --repair-rounds 2

# Add the reasoning agent (three-tier plan injected into the optimiser prompt)
python3 pipeline.py --dataset pie --samples 5 --reason

# Full agentic loop (reasoner + Critic between repair rounds)
python3 pipeline.py --dataset pie --samples 5 --reason --agentic --repair-rounds 2
```

Each run produces a fresh `results/run_<timestamp>/` directory with:
- `meta.json`             — exact config snapshot, for reproducibility
- `results.jsonl`         — one line per sample, full schema
- `results.json`          — same data, prettified array form
- `summary.txt`           — per-sample pass/fail/speedup table + aggregates
- `samples/<id>/`         — per-sample artefacts (prompts, candidates, diffs, gprof, …)

---

## 3. CLI reference

### 3.1 Sample selection

| Flag | Default | Effect |
|---|---|---|
| `--dataset {pie,synthetic}` | `synthetic` | PIE = CodeNet speedup pairs; synthetic = bug-fix samples in `data/bugs.py` |
| `--samples N` | 5 (PIE) / all (synth) | how many samples to run |
| `--id ID` | — | run only the sample with this id |
| `--pie-min-improvement F` | 30.0 | keep PIE pairs with ≥ F% oracle improvement |
| `--pie-max-lines N` | 80 | drop pairs whose slow code exceeds N LOC |
| `--pie-min-baseline-cputime MS` | 0 | drop pairs with `cpu_time_v0 < MS` (use ≥ 100 for meaningful gprof signal) |
| `--pie-max-tests N` | unlimited | cap test cases per problem (relevant when `merged_test_cases/` is present) |

### 3.2 Modes

| Flag | Default | Effect |
|---|---|---|
| `--mode static\|dynamic\|profiling\|all` | `all` | which mode(s) to run |
| `--mode static,profiling` | — | comma-separated subset works too |

### 3.3 LLM behaviour

| Flag | Default | Effect |
|---|---|---|
| `--backend {local,anthropic}` | `local` | which LLM backend |
| `--model NAME` | `Qwen/Qwen2.5-Coder-7B-Instruct` | HF model id (local) |
| `--k N` | 1 | candidates per (sample, mode); `k>1` enables sampling |
| `--temperature F` | 0.6 | only used at `k>1` |
| `--seed N` | 0 | sampling seed (vary across runs to estimate variance) |
| `--force-4bit` | off | force NF4 quantisation regardless of free VRAM |
| `--repair-rounds N` | 0 | self-repair retries when all `k` initial candidates fail |
| `--iterate-speedup-rounds N` | 0 | mutate-on-pass retries asking for a strictly faster version |

### 3.4 Prompt-content flags

| Flag | Default | Effect |
|---|---|---|
| `--no-problem-statement` | (statement on) | drop the problem statement from the prompt |
| `--full-problem-statement` | (constraints only) | include the full statement, not just `Constraints:` block |
| `--no-test-case-sample` | (sample on) | drop the worked test case from the prompt |
| `--no-complexity-hint` | (hint on) | drop the LLM-predicted Big-O block |
| `--no-gcov` | (gcov on) | skip gcov line-level execution counts in profiling mode |
| `--tag-advice` | off | add tag-conditional advice (regresses correctness on Qwen-7B; opt-in) |
| `--reason` | off | run the reasoning agent (three-tier plan) before the optimiser |
| `--agentic` | off | run the Critic agent between repair rounds |

---

## 4. Repository layout

```
.
├── README.md                  # ← you are here
├── architecture.md            # agentic-pipeline design doc
├── requirements.txt           # Python deps
├── pipeline.py                # entry point — orchestrator + CLI
├── local_llm.py               # HuggingFace local-model inference
├── llm_agent.py               # Anthropic API backend (alternative)
├── compiler.py                # compile + run C++ with timing
├── profiler.py                # gprof / perf / gcov + prompt formatters
├── config.py                  # paths, compile flags, timeouts, model default
├── reasoner.py                # reasoning agent (three-tier plan, v2)
├── agent_state.py             # AgentState + Attempt dataclasses
├── agent_critic.py            # Critic agent — diagnose + emit C++ patch
├── data/
│   ├── bugs.py                # synthetic bug samples (no LLM cost)
│   ├── pie_loader.py          # PIE JSONL → sample dicts; merged-or-public test loader
│   ├── problem_classifier.py  # LLM-side problem → tag, JIT-cached
│   ├── complexity_predictor.py# LLM-side source → Big-O, JIT-cached
│   ├── problem_tags_*.csv     # disk cache (per classifier_id)
│   ├── code_complexity_*.csv  # disk cache (per predictor_id)
│   ├── reasoning_*.csv        # disk cache (per reasoner_id × mode)
│   └── critic_*.csv           # disk cache (per critic_id)
├── tools/
│   ├── extract_pie_code.py    # write PIE (slow, fast) pairs to disk
│   ├── extract_profile.py     # run gprof/perf/gcov for inspection
│   ├── backfill_summary_txt.py# regenerate summary.txt for an older run
│   ├── backfill_diffs.py      # regenerate clang-format-normalised diffs
│   ├── split_results.py       # split a results.jsonl by mode/outcome
│   └── jsonl_to_json.py       # convert .jsonl → pretty .json
├── pie-perf/                  # NOT in this repo — clone separately (see §1.4)
├── workspace/                 # transient compile artefacts (gitignored)
└── results/                   # per-run output directories (gitignored)
```

---

## 5. Pipeline at a glance

```
PIE sample = (v0_slow.cpp, v1_fast.cpp, test_cases, problem_statement)
                              │
                              ▼
     ┌────────────────────────────────────────────────┐
     │  Baseline: compile v0 → run on each test case  │
     │  → mean_ms                                      │
     └────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
     STATIC               DYNAMIC               PROFILING
     code only        + runtime diff       + gprof + perf + gcov
        │                     │                     │
        ▼ (optional: reason → critic on failure)    ▼
     LLM call → k candidates → compile + run → pick winner
        │                     │                     │
        ▼                     ▼                     ▼
     winner.cpp           winner.cpp           winner.cpp
     speedup vs v0        speedup vs v0        speedup vs v0
```

For each (sample, mode) the orchestrator runs:
1. **Initial pass** — one LLM call producing `k` candidates
2. **Self-repair** if all `k` fail (up to `--repair-rounds N`)
3. **Iterate-on-speedup** if any candidate passes (up to `--iterate-speedup-rounds N`)

`--reason` adds a three-tier optimisation plan (reasoner.py) to every LLM
call. `--agentic` adds a structured Critic diagnosis between repair rounds.
Full design in [`architecture.md`](architecture.md).

---

## 6. Output schema

Per-run directory:

```
results/run_<timestamp>/
├── meta.json                 # CLI flags + run config
├── results.jsonl             # one line per sample
├── results.json              # same content, pretty-printed array
├── summary.txt               # human-readable table + aggregates
└── samples/<sample_id>/
    ├── v0_slow.cpp           # the slow input
    ├── v1_fast.cpp           # the gold-fast oracle (PIE only)
    ├── sample_meta.json
    ├── baseline_timing.json
    ├── problem_statement.txt
    ├── test_case_sample.txt
    ├── complexity_analysis.json / complexity_block.txt
    ├── tag_advice.txt        # if --tag-advice
    ├── reasoning_<mode>.txt  # if --reason
    ├── agent_trace_<mode>.json # if --agentic; per-attempt trajectory
    ├── gprof_flat.txt        # if profiling mode ran
    ├── perf_stat.txt
    ├── gcov_raw.txt / gcov_hot_lines.json
    ├── prompt_runtime_feedback.txt   # exact prompt blocks per mode
    ├── prompt_profile_summary.txt
    └── <mode>/               # static/, dynamic/, profiling/
        ├── prompt.txt        # the assembled LLM prompt for the initial pass
        ├── candidate_0.cpp … candidate_<k-1>.cpp
        ├── candidate_<i>_run.json
        ├── candidate_<i>_vs_v0.diff
        ├── repair_round_<N>_prompt.txt   # if self-repair fired
        ├── winner.cpp
        └── winner_vs_v0.diff
```

A line in `results.jsonl` (PIE):

```jsonc
{
  "id": "pie_p03146_s047505757",
  "source": "pie",
  "problem_id": "p03146",
  "improvement_frac_oracle": 89.4,    // PIE metadata; not used by the loop
  "baseline":  { "compiled": true, "passed": true, "mean_ms": 168.7 },
  "static":    { "passed": true, "mean_ms": 20.5, "speedup": 8.20,
                 "k_correct": 5, "candidates_summary": [/*...*/],
                 "repair_history": [/*...*/] },
  "profiling": { /* ... */ }
}
```

---

## 7. Models tested

Trade-off: 7B fits in fp16 on a single 24 GB card; larger models need 4-bit
or distributed inference. The auto-fallback in `local_llm.py` quantises to
NF4 if free VRAM < 15 GB at load time. `--force-4bit` overrides.

| Model | HF ID | fp16 VRAM | 4-bit VRAM |
|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct (default) ⭐ | `Qwen/Qwen2.5-Coder-7B-Instruct` | 14 GB | 5 GB |
| DeepSeek-Coder-6.7B-Instruct | `deepseek-ai/deepseek-coder-6.7b-instruct` | 13 GB | 4 GB |
| CodeLlama-7B-Instruct | `codellama/CodeLlama-7b-Instruct-hf` | 13 GB | 4 GB |
| CodeLlama-13B-Instruct | `codellama/CodeLlama-13b-Instruct-hf` | 26 GB ❌ | 7 GB |
| Qwen2.5-Coder-14B-Instruct | `Qwen/Qwen2.5-Coder-14B-Instruct` | 28 GB ❌ | 9 GB |

Note that **KV cache** dominates memory at higher `k`. At `k=8` with rich
prompts on a 7B model, peak VRAM is ~21 GB just for the KV cache. Drop `k`
or set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` to mitigate.

---

## 8. Tools (under `tools/`)

### `extract_pie_code.py`
Write PIE `(slow, fast)` source pairs and metadata to a browseable
directory tree — useful for manual diff inspection.

### `extract_profile.py`
Run the full profiling pipeline (gprof, perf, gcov, prompt-formatting) and
write every intermediate to disk — useful for understanding what the LLM
sees in dynamic/profiling modes.

### `backfill_summary_txt.py` / `backfill_diffs.py`
Regenerate `summary.txt` and `*_vs_v0.diff` artefacts for older runs that
predate those features.

### `split_results.py`
Split a `results.jsonl` by mode × outcome for cross-run analysis.

See `--help` on each script for the full CLI.

---

## 9. Notable design points

These are documented in detail in [`architecture.md`](architecture.md) and
the per-run error reports under `results/run_*/`. In one paragraph each:

- **Oracle speedup is never used inside the loop.** It appears only as a
  reference column in `summary.txt`. All in-loop comparisons are
  self-relative (winner vs previous winner) to avoid eval-time leakage.
- **JIT LLM-side caches.** The problem classifier, complexity predictor,
  reasoning agent, and Critic all cache their outputs to CSV in `data/`
  keyed by a per-version `_id`. Bump the `_id` to invalidate.
- **Mode isolation.** The reasoner and Critic see only the signals the
  current mode is allowed to: `static` sees code + problem statement;
  `dynamic` adds runtime diff; `profiling` adds the full profile summary.
- **Critic v2 (current).** Emits a literal C++ patch in `replacement_block`,
  not a free-text suggestion. Uses delta-debug bisection against v0 to
  shrink failing stdin to a minimal example before diagnosing. See
  `architecture.md §10` for the v1 → v2 changelog and the run that motivated
  it.

---

## 10. License & acknowledgments

- PIE dataset: [pie4perf.com](https://pie4perf.com), licensed per the upstream
  [pie-perf](https://github.com/madaan/pie-perf) repository.
- CodeNet problem statements (English-translated) ship with the PIE dataset.
- Pipeline code in this repository: research / educational use.
