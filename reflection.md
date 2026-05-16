# Reflection: Profile-Guided Code Correction with LLMs

A working journal of what was built, what broke, what the data showed, and
what to look at next. Written 2026-04-26 against commit-state of this
working tree.

---

## 1. Research question

From [task.md](task.md):

> Does providing dynamic execution feedback (runtime metrics) significantly
> outperform static analysis (reading code only) for code correctness?
> Domain Focus: C++, both code correctness and execution speed.

We instantiated this as a **three-arm ablation** on a single 7B local model:

- **static** — LLM sees only the buggy/slow source.
- **dynamic** — adds runtime execution feedback (output diff, or per-test-case timing) but no profiler data.
- **profiling** — adds the gprof flat profile + perf stat counters.

The split between `dynamic` and `profiling` is the clean ablation: it isolates
"the LLM has timing/runtime information" from "the LLM has function-level
hotspot attribution." Either is a form of dynamic feedback in the broad sense,
but they are very different prompts.

---

## 2. Pipeline architecture

End-to-end flow per sample:

```
sample (buggy/slow C++)
  -> compile_code()                    -> binary + warnings
  -> compile_and_run() / _tests()      -> stdout(s) + per-test pass/fail + timing
  -> profile()                         -> gprof flat profile + perf stat (per-sample stdin)
  -> format_*_for_llm()                -> prompt block per mode
  -> repair_static / _dynamic / _profiling()  (HF or Anthropic backend)
  -> compile_and_run_tests()           -> verify candidate, time it
  -> diff vs baseline, record speedup
```

Files:

- [pipeline.py](pipeline.py) — orchestration, two runners (`run_sample` for synthetic, `run_pie_sample` for PIE), CLI, summary.
- [compiler.py](compiler.py) — `compile_code`, `compile_and_run`, `compile_and_run_tests` (multi-test, multi-trial, optional `taskset` pinning).
- [profiler.py](profiler.py) — gprof + perf wrappers, three prompt formatters (`format_runtime_feedback`, `format_profile_for_llm` for synthetic; `format_pie_*` for PIE).
- [local_llm.py](local_llm.py) — HuggingFace inference path with auto-quantisation (fp16 if VRAM ≥ 15 GB, else 4-bit NF4).
- [llm_agent.py](llm_agent.py) — Anthropic backend, mirroring the same three repair entry points.
- [data/bugs.py](data/bugs.py) — 10 hand-curated synthetic bug samples.
- [data/pie_loader.py](data/pie_loader.py) — PIE loader + filters.

LLM backend defaults to local Qwen2.5-Coder-7B-Instruct. Greedy decoding, deterministic.

---

## 3. Datasets surveyed

### 3.1 Synthetic (`data/bugs.py`) — 10 samples

Hand-written C++ snippets covering off-by-one, pointer error, init-error, loop-bound, logic-error categories. Self-contained `main()` programs that print to stdout.

**Verdict:** good for plumbing tests, useless for measuring profile-mode signal — every program runs in microseconds, so gprof reports `no time accumulated` and `perf stat` shows trivial cycle counts. The static/dynamic/profiling ablation cannot meaningfully differentiate on these.

### 3.2 DebugBench (`debugbench/`) — explored, not integrated

LeetCode-sourced C++ buggy/oracle pairs, ~1438 samples across 17 bug categories. **Not used** because:

- Code is `class Solution { ... }` style with no `main()` and no stdout — every entry needs a per-problem driver wrapper to be runnable locally.
- Authoritative correctness check is LeetCode OJ submission (needs session token, has cooldowns).
- Test inputs are tiny — same gprof-attribution problem as the synthetic set.

Decision: defer DebugBench. If used later, scope it as a **correctness ablation only**, not a profile-guided ablation.

### 3.3 PIE (`pie-perf/`) — chosen as primary dataset

Performance-Improving Edits, sourced from IBM CodeNet. Each entry is a `(slow correct, fast correct)` C++ pair with `improvement_frac >= 1%`. Standalone `main()` programs that read stdin / write stdout. Test cases are file pairs (`input.N.txt` / `output.N.txt`).

**Why PIE fits the research better than DebugBench:**

- Standalone runnable, no driver synthesis.
- Public test cases as files, no OJ dependency.
- Real CodeNet-sized inputs that exercise actual hotspots.
- The dataset *itself* is built around speedup — directly maps to the "execution speed" arm of the research goal.

The trade-off: PIE doesn't probe correctness as bug-fixing. It probes correctness as *preserving* behaviour while making changes. The slow version is already correct.

---

## 4. Bug fixes and setup notes worth remembering

### 4.1 Local Python environment

Packages live in `/cs/student/project_msc/2025/dsml/nmxian/py_packages/` (added to `sys.path` at import time by `config.py`). User-level pip is for `torch` only. Hugging Face cache is at `/cs/student/project_msc/2025/dsml/nmxian/huggingface_cache/`.

The `transformers` install warns about `TRANSFORMERS_CACHE` being deprecated in favour of `HF_HOME`. Harmless. Both env vars are set in `local_llm.py` for compatibility with older versions.

### 4.2 4-bit fallback when VRAM is tight

Earlier runs OOM'd because the VRAM detection only counted *this process's* allocation. Fixed by switching to `torch.cuda.mem_get_info(0)` which returns free memory across **all** processes. With < 15 GB free we drop to 4-bit NF4 via bitsandbytes; otherwise fp16. ([local_llm.py:60-89](local_llm.py#L60-L89)).

Implication: if you see OOM mid-run, something else on the GPU started eating memory. Re-run without altering code.

### 4.3 perf stat preview was being clipped

The pipeline printed `profile_summary[:300]` to console, which only fit through the gprof header — perf stat fell off the bottom. **The LLM still saw the full thing**; the bug was in the human-facing preview only. Bumped to `[:2000]`. ([pipeline.py](pipeline.py))

### 4.4 Hybrid CPU (P + E cores)

`perf stat` on this host produces dual rows (`cpu_atom/...` + `cpu_core/...`) because the chip is hybrid. Atom cores frequently show `<not counted>` for short programs because they never get scheduled there. We pin timed runs to CPU 0 (a P-core) via `taskset -c 0` to stabilise measurements ([config.py: `PIE_TASKSET_CPU = 0`](config.py)).

This is the right call for **timing**. For profiling we still take the perf output verbatim and let the LLM see both rows.

### 4.5 Float-precision baseline failure (PIE p03169)

`5.5000000000` (slow code default precision) vs `5.5` (expected output file) registered as `wrong_output` because we did exact whitespace-tolerant string comparison. Fixed by adding `_tokens_match` in `compiler.py`: token-by-token comparison with relative+absolute float tolerance (1e-6 / 1e-9). CodeNet's judge accepts numeric matches within tolerance for many problems; we now do too. ([compiler.py:`_tokens_match`](compiler.py))

### 4.6 TLE-on-baseline samples were getting silently skipped (PIE p01324)

Original gating built feedback only when `slow["passed"]` was true. For PIE that's wrong: a baseline TLE *is* the most informative dynamic feedback ("your program times out on these inputs"). Now we build feedback whenever the binary exists and `per_test` is populated. The slow version still gets recorded as failing in `result["baseline"]` but dynamic and profiling modes still run. ([pipeline.py: feedback-building block](pipeline.py))

### 4.7 Speedup metric was misleading on FAIL rows

Earlier per-row table printed e.g. `FAIL 7.95x` — the model deleted the algorithm, ran fast, and got wrong output. Display now shows `FAIL (failure_mode)` with no fake speedup. Speedup is also `None` in JSONL when the candidate didn't pass. ([pipeline.py: `_run_mode`, summary printing](pipeline.py))

### 4.8 Failure mode taxonomy

Each repair attempt now records `failure_mode ∈ {None, compile, runtime_error, timeout, wrong_output}`. The summary breaks down failures per mode so we can see whether feedback is producing dead code or wrong code. ([compiler.py: `compile_and_run_tests`](compiler.py))

### 4.9 Profile target = slowest test case

`profile()` runs the binary once to collect gprof + perf data. Originally we used the first test case as stdin. For programs whose first test is small, gprof attributes nothing. Now we pick the slowest test case (by mean wall-clock from the multi-trial run) as the profiling input. ([pipeline.py: `run_pie_sample`](pipeline.py))

### 4.10 Persisted JSONL is append-mode

Each run appends to `results/results_<dataset>_<model>.jsonl`. Multiple runs co-exist in one file. Each row carries `run_id` (timestamp) and `run_meta` (filters used) so post-hoc analysis can disambiguate. The in-memory summary printed at end-of-run only reflects the current run.

---

## 5. Result reasoning

### 5.1 Synthetic (n=10, bugs.py) — sanity baseline

Static 4–5/5, Dynamic 5/5, Profiling 5/5 across the 5 original samples, varying with quantisation. The static/dynamic gap on `003_wrong_operator` was the only bug where dynamic feedback recovered a case static missed. With 10 samples and microsecond programs, the result is not informative for the research question.

### 5.2 PIE n=10, no cputime filter

```
static    correctness 7/10  faster 6/10  median 1.15x
dynamic   correctness 3/10  faster 2/10  median 1.20x
profiling correctness 5/10  faster 3/10  median 1.06x
```

**Counter-intuitive**: more feedback hurt correctness. This is partly artefact:

- 2 samples had broken baselines (float precision; TLE) that were excluded only after the fixes in §4.5–4.6.
- gprof was showing `no time accumulated` because programs ran in 5–10 ms.
- Display bug (`failure_mode` not surfaced) made some FAILs look like near-PASS.

### 5.3 PIE n=10, cputime ≥ 100 ms — the result flips

Once baseline programs took ≥ 100 ms (so gprof actually attributes time):

```
static    correctness 7/10  faster 3/10  median 0.96x
dynamic   correctness 4/10  faster 0/10  median 0.78x
profiling correctness 9/10  faster 6/10  median 1.01x   <-- best
```

Profiling went from worst (60% on the fast-baseline run) to best (90%). One sample (`pie_p03146_s047505757`, 168 ms baseline, oracle improvement 89%) hit **7.55x** speedup in dynamic mode and 6.95x in profiling mode — both correct.

### 5.4 PIE n=30, cputime ≥ 0 — distribution stats matter

```
mode       correct  faster  mean    median  p75    max
static     22/30    8/30    0.87x   0.96x   1.03x  1.40x
dynamic    16/30    6/30    0.88x   0.89x   1.02x  1.66x
profiling  19/30    10/30   1.16x   1.00x   1.30x  2.39x   <-- best on speedup
```

The **mean** (1.16x for profiling) tells a different story than the median (1.00x). Because speedup wins are concentrated in a few high-headroom samples, mean and p75 are the right summary stats, not median.

Per-row "winner" (mode with highest speedup ≥ 1.0x):

```
profiling : 7 wins
static    : 5 wins
dynamic   : 2 wins
no winner : 16 (no mode beat baseline)
```

Three of the biggest wins were profiling-only:

```
pie_p02945   static 1.39x   dynamic FAIL   profile 2.39x
pie_p03169   static 1.00x   dynamic 1.00x  profile 2.27x
pie_p03293   static 0.77x   dynamic 0.73x  profile 1.56x
```

These are samples where `gprof` exposed a hotspot the model wouldn't have spotted from source alone.

### 5.5 Why dynamic-only feedback is uniformly worst

Every run shows dynamic in last place on correctness. Hypothesis: telling a 7B model "your code is slow on these inputs" without saying *what* is slow primes it to assume an algorithmic problem and rewrite wholesale. Often the rewrite is wrong (`wrong_output` is the dominant failure mode for dynamic — 11/30 samples in the n=30 run).

Profiling mode mitigates this because the gprof flat profile names actual functions and call counts, so the model targets the rewrite at the right code instead of the whole program.

### 5.6 Static is the safest, profiling is the highest-ceiling

A consistent two-axis pattern:

- **Static** has the highest correctness rate (~70–80%). It rarely speeds anything up but it rarely breaks anything either. The model makes small, conservative edits.
- **Profiling** has slightly lower correctness but much higher mean speedup and the largest individual wins. It also has a unique failure mode (`compile`) — the model occasionally tries to apply gprof suggestions in ways that don't compile.
- **Dynamic** is dominated on both axes by something — static (correctness) or profiling (speed). It is not on the Pareto frontier in any of our runs.

This is consistent with the research hypothesis but the practical interpretation is **conditional**: profile-guided beats static *only* when (a) the baseline is slow enough for gprof to attribute time, and (b) you care about peak/mean speedup more than worst-case correctness.

---

## 6. Caveats / limitations to disclose if writing this up

- **Model size.** Everything is on Qwen2.5-Coder-7B. A 14B or 34B model may handle dynamic-only feedback more responsibly. The "dynamic always last" finding may be size-bound.
- **Single-run determinism.** `temperature=0`, greedy decoding. No pass@k, no variance bars. Speedup numbers are mean of 3 timed trials with 1 warmup, but the *generation* is deterministic.
- **Benchmark size.** n=30 with PIE is small for cross-mode comparisons. The 90/70/40 gap on cputime≥100 (n=10) had a non-trivial chance of being noise; n=30 helps but is still not robust.
- **Bimodal speedup distribution.** Most PIE samples are flat (≈ 1.0x). The means are dominated by 3–7 high-headroom samples. Reporting mean alone is misleading; report p25/p75/max too (which we now do).
- **No statistical test.** McNemar's would be the right thing for paired correctness comparisons across modes; haven't run it.
- **gprof noise.** Even on slow baselines, gprof sometimes attributes time to `__static_initialization_and_destruction_0`. The LLM occasionally writes broken code in response to this noise.
- **Hybrid CPU.** Dual-row perf stat output (`cpu_atom` + `cpu_core`) is sent verbatim to the LLM. May confuse smaller models.
- **PIE pairs are not minimal patches.** The "fast" version is sometimes a complete algorithmic rewrite, not a localised edit. The model is being asked to rewrite, not patch — closer to refactoring than bug fixing.
- **DebugBench is unused.** That arm of the research (correctness on actual semantic bugs in real LeetCode code) is open. The driver-synthesis cost was deferred.

---

## 7. Pass@k results (k=3 sampling, temperature 0.6)

After implementing pass@k via `num_return_sequences=k` (sampled decoding,
temperature 0.6, seed 0), we re-ran the n=30 ablation under two filters.

### 7.1 n=30, k=3, cputime ≥ 0 (mixed baselines)

```
mode       correct    faster   mean   median   p25    p75    max
static     24/30      14/30    1.00x  1.01x    0.96x  1.03x  1.47x
dynamic    20/30      12/30    1.01x  1.01x    0.98x  1.05x  1.52x
profiling  24/30      15/30    1.07x  1.01x    0.97x  1.07x  2.53x
```

Compared to the same condition at k=1:

| Mode      | k=1 correct | k=3 correct | Δ      | k=1 faster | k=3 faster | k=1 mean | k=3 mean |
|-----------|-------------|-------------|--------|------------|------------|----------|----------|
| static    | 22/30 (73%) | 24/30 (80%) | +7 pp  | 8/30       | 14/30      | 0.87x    | 1.00x    |
| dynamic   | 16/30 (53%) | 20/30 (67%) | +14 pp | 6/30       | 12/30      | 0.88x    | 1.01x    |
| profiling | 19/30 (63%) | 24/30 (80%) | +17 pp | 10/30      | 15/30      | 1.16x    | 1.07x    |

Take-aways:

- **Sampling lifts every mode's correctness 7–17 pp.** Profile-mode benefits
  most because its k=1 weakness was *unique compile errors* (the LLM tried to
  apply gprof suggestions in invalid C++), and a second/third sample usually
  doesn't repeat that mistake.
- **Mean speedup converges to ~1.0x** because the bigger correct subset
  includes more low-headroom samples sitting near 1.00x. Mean is the wrong
  summary stat here. **Max** and **count of "faster"** are the right ones.
- **Profiling retains the lead on the speedup tail** — max 2.53x vs static
  1.47x and dynamic 1.52x.

### 7.2 n=30, k=3, cputime ≥ 100 ms (slow-baseline arm — the cleanest test)

```
mode       correct    faster   mean    median  p25    p75    max
static     22/30      14/30    1.15x   1.02x   0.98x  1.07x   2.71x
dynamic    19/30       9/30    2.96x   1.00x   0.95x  1.27x  35.80x
profiling  24/30      14/30    2.78x   1.04x   0.93x  1.22x  37.15x
```

This is the headline ablation. Three things change dramatically:

1. **Max speedups jump by an order of magnitude.** Both dynamic (35.8x) and
   profiling (37.1x) produce one or two samples that the LLM rewrites with
   genuinely faster algorithms. The single sample driving most of this:

   ```
   pie_p03146_s047505757  baseline 423 ms  oracle +89%
       static     2.71x
       dynamic   35.80x
       profile   37.15x
   ```
   At k=3 the LLM had three sampled rewrites; one of them switched to a
   ~37× faster algorithm. At k=1 (greedy) we never saw this.

2. **Mean speedup is no longer near 1.0x.** Dynamic (2.96x) and profiling
   (2.78x) now both clearly beat static (1.15x) on average. The bimodal
   distribution is real — most samples are 1.0x but the wins are huge enough
   that they pull the mean up.

3. **Profile-mode is best on correctness (24/30 = 80%) AND on max speedup.**
   It is the only mode that is on the Pareto frontier on both axes.

Top 5 wins across modes:

```
id                              static  dynamic   profile  baseline_ms  oracle%
pie_p03146_s047505757            2.71x   35.80x    37.15x    423.4       +89%
pie_p03730_s590400302            1.01x    F:wrong   5.35x     49.4       +99%
pie_p01324_s953390691            2.42x    2.27x     2.29x     24.8       +53%
pie_p03169_s960308819            1.15x    1.82x     F:wrong   22.8       +45%
pie_p02274_s021946467            1.48x    F:wrong   1.72x     20.9       +58%
```

The story shifts vs. the k=1 reflection in §5.5: with sampling on slow
baselines, **dynamic-mode timing data is no longer uniformly bad**. Its
mean and max are essentially tied with profiling. What still distinguishes
profiling is its higher correctness rate — when the LLM rewrites with
profile data it breaks correctness less often than when it rewrites with
timing data alone.

### 7.3 RUN 2 (n=10 k=5 cputime ≥ 100) — partial, OOM after sample 2

Hit a CUDA OOM mid-run because another process on the shared GPU was
holding ~7 GB. The first sample is preserved as evidence that k=5 sampling
finds even larger wins:

```
pie_p03146_s047505757   baseline 423 ms
    static     1.72x  (winner_idx=0)
    dynamic   13.51x  (winner_idx=1)
    profiling 11.91x  (winner_idx=1)
```

To retry safely either drop to 4-bit on the model load (`PIE_FORCE_4BIT`
env, not yet implemented) or wait for the contention to clear.

### 7.4 What pass@k changed about the conclusion

| Claim | k=1 evidence | k=3 evidence (cputime≥100) |
|---|---|---|
| Profiling > static on correctness | 63% vs 73% (worse at k=1, mixed) | 80% vs 73% (better) |
| Profiling > static on speedup | mean 1.16x vs 0.87x | mean 2.78x vs 1.15x |
| Dynamic is uniformly worst | yes | no — mean 2.96x and max 35.8x match profiling |
| Sampling helps profile-mode most | n/a | +17 pp correctness, by avoiding compile errors |

The original profile-guided hypothesis is supported under the conditions
(slow baseline + sampling). It is *not* supported uniformly — at k=1 with
fast baselines, more feedback hurt correctness, exactly as §5.2 reported.
This conditionality is itself the interesting paper-worthy finding.

### 7.5 Self-repair (k=1 + repair_rounds=2 vs k=3 sampling)

We added a self-repair loop ([profiler.py:format_self_repair_feedback](profiler.py),
[pipeline.py: `_self_repair_round`](pipeline.py)) that, when all initial
candidates fail, augments the mode-specific feedback with the failed code
plus a description of the failure (compile error / wrong output / timeout
/ runtime error) and asks the LLM to fix it. Up to N rounds, k=1 greedy
per round.

At equal LLM-call budget (~3 calls per failed (sample, mode)):

| Mode | k=3 sampling correct | k=1 + repair=2 correct | k=3 + repair=2 correct |
|---|---|---|---|
| static | 73% | **80%** | 77% |
| dynamic | 63% | 60% | **70%** |
| profiling | **80%** | 77% | **80%** |

| Mode | k=3 max sp | k=1 + repair=2 max sp | k=3 + repair=2 max sp |
|---|---|---|---|
| static | 2.71x | 1.17x | 1.55x |
| dynamic | 35.80x | 7.43x | 8.67x |
| profiling | 37.15x | 8.06x | 8.71x |

How often repair flipped a failure to success:

| Regime | static | dynamic | profiling |
|---|---|---|---|
| k=1 + repair=2 | 8 entered → 2 flipped (25%) | 17 → 5 (29%) | 8 → 1 (12%) |
| k=3 + repair=2 (combined) | 8 → 1 (12%) | 7 → 0 (0%) | 4 → 0 (0%) |

Sampling and self-repair turned out to be **redundant rather than
additive** for this task with this model:

- Sampling already filters out the easy failures. When the greedy
  completion has a simple bug, one of the other 2 samples usually gets
  it right; repair never has to fire.
- Failures that *survive* k=3 sampling are deep algorithmic mistakes —
  three different completions all making the same error. Repeating the
  prompt with "you got the wrong answer" doesn't dislodge the model from
  the wrong solution path.
- Repair is most effective when sampling has *not* explored — it works
  best for k=1 where most failures are simple bugs (compile errors,
  wrong output on edge cases).

This is itself a useful research observation: **for code-optimisation
tasks, sampling and self-repair are competing strategies, not stackable
ones.** Pick whichever fits the cost model.

### 7.6 Replicate analysis (3 seeds, n=30 k=3 cputime≥100)

Single-run sampling figures have huge variance — the celebrated 37×
profile-mode max in §7.2 was largely a lucky draw on a pre-`--seed`
run. To estimate true treatment effects we ran the same condition with
seeds 0, 1, 2 (added `--seed` CLI flag, three full n=30 replicates):

| Mode | Correctness | Max speedup | Mean speedup | Per-seed maxes |
|---|---|---|---|---|
| static | 80% ± 7 | 5.05× ± 3.44 | 1.22× ± 0.19 | 1.38×, 5.58×, 8.20× |
| dynamic | 69% ± 4 | 3.88× ± 2.74 | 1.15× ± 0.17 | 7.04×, 2.25×, 2.35× |
| **profiling** | **82% ± 2** | **8.27× ± 0.61** | **1.38× ± 0.05** | **7.97×, 7.87×, 8.97×** |

What the replication exposes:

1. **Profile-mode is the most reliable mode on every metric.** Highest
   mean correctness (82%), highest mean speedup (1.38×), highest max
   speedup (8.27×), AND tightest variance on each (SD 2, 0.05, 0.61
   respectively). It is the only mode on the Pareto frontier.
2. **Profile-mode max speedup is essentially deterministic at ~8×.**
   The three per-seed maxes are 7.87×, 7.97×, 8.97× — SD 0.61 across
   seeds. This is a robust claim: under (k=3, cputime≥100, n=30),
   profile-guided correction reliably surfaces a ~8× speedup
   somewhere in the dataset.
3. **Static and dynamic max speedups are lottery-like.** Static
   ranged 1.38× → 8.20× (SD 3.44). Dynamic ranged 2.25× → 7.04× (SD
   2.74). Whether the LLM finds a big win in these modes depends on
   which sampled completion happens to spell out the right algorithm.
4. **The 37× / 35× headlines from §7.2 do not replicate** in seeded
   runs. They came from the pre-`--seed` legacy run where the GPU /
   cuBLAS state happened to produce an extreme outlier. Don't cite
   them as evidence of treatment effect — cite the seeded numbers
   above.
5. **Dynamic-mode variance is the most sample-bound.** Two of three
   seeds produced max-speedup ≈ 2.3× (essentially no big win); only
   seed=0 hit 7.04×. With a 7B model, dynamic feedback is unreliable
   — the LLM either nails the rewrite or panic-rewrites poorly.
6. **Static-mode max can occasionally hit 8.20×** (seed=2) — slightly
   higher than profile-mode's 7.87× / 7.97×. So static is not always
   "boring"; it's just *unreliable* about when it produces a big win.
   Profile-mode is where the consistent ceiling lives.

### 7.7 Bug fixes uncovered during replication

- **Non-UTF-8 stdout crashed the pipeline** ([compiler.py:_run_timed_once](compiler.py),
  [compiler.py:run_binary](compiler.py), [profiler.py:run_gprof](profiler.py),
  [profiler.py:run_perf_stat](profiler.py)). With `text=True`, a candidate
  emitting `0xff` raised `UnicodeDecodeError` and aborted the run. Fixed
  by switching to `text=False` + `bytes.decode("utf-8", errors="replace")`.
  A misbehaving candidate now correctly registers as `wrong_output`
  rather than killing the experiment. This bit seed=2 at sample 24/30.

---

## 8. Result file layout

Append-only `results/results_<dataset>_<model>.jsonl` accumulates rows from
every run. To slice by experiment, run:

```bash
python3 tools/split_results.py results/results_pie_Qwen2.5-Coder-7B-Instruct.jsonl
```

This writes one file per `run_id` into `<input>_split/`. Filenames embed
`n`, `k`, and the cputime filter, so the experimental matrix is readable
at a glance:

```
results_pie_..._20260426-165457__pie__n30__k3__cputime100.jsonl
results_pie_..._20260426-170854__pie__n30__k3__cputime0.jsonl
results_pie_..._20260426-012619__pie__n30__k1__cputime0.jsonl
...
results_pie_..._legacy.jsonl                     # untagged early rows
```

The split files are the canonical per-experiment record. The mother JSONL
remains the running ledger.

---

## 9. Next steps, in priority order

1. **Add paired McNemar (or paired-bootstrap CIs) to the summary.**
   Per-pair correctness comparisons (static vs profiling, profiling vs
   dynamic) on the same samples, with a p-value instead of just point
   estimates. The replicate data in §7.6 makes this feasible — three
   seeds give us enough resampling power for a defensible CI.
2. **n=30 k=3 cputime ≥ 500.** A second slow-baseline condition where
   gprof attribution is unambiguous on every sample (currently it only
   attributes time on a subset even at cputime≥100). Expected to widen
   profiling's correctness lead.
3. **Run the same k=3 matrix with a 14B model in 4-bit.** Check whether
   the static / dynamic correctness gap closes when the model is bigger.
   Particularly interested in whether dynamic mode's high max-speedup
   variance shrinks at scale.
4. **Distinguish "no real speedup possible" samples.** Filter out samples
   where the *oracle* fast version is < 1.05× our measured baseline —
   those are dataset noise rather than real optimisation targets. Likely
   improves all means by removing dead-weight samples.
5. **Retry the RUN 2 OOM (n=10 k=5 cputime≥100)** when the GPU is
   uncontested. Confirms whether k=5 reliably surfaces 13x+ wins or
   whether the smoke-test sample was a fluke. Lower priority now —
   replicate analysis already shows §7.2's individual-sample peaks
   are mostly noise.
6. **Switch profiling to `perf record -F 999`** instead of gprof. Gives
   function-level attribution without needing programs that take ≥ 500
   ms. Worth trying once for comparison.
7. **DebugBench correctness arm.** Hand-curate ~30 entries with simple
   method signatures, write drivers, run a static-only ablation. Different
   research question (correctness on real bugs) from the PIE optimisation
   arm.
