# Improvement Suggestions for the LLM Code-Repair Pipeline

A running list of techniques to try beyond the four already implemented
(better prompt, hotspot annotations, iterate-on-speedup, multi-test repair).
Each item names the failure mode it targets, sketches an implementation,
and estimates cost.

Ordered roughly by expected impact on the current PIE C++ pipeline running
Qwen2.5-Coder-7B-Instruct.

---

## High-leverage

These should produce visible movement in correctness or speedup metrics
on the existing 30-sample benchmark.

### 1. Use the problem statement as context

**Idea.** PIE ships English problem statements in
`pie-perf/data/problem_statements_translated.zip` (4001 HTML files, one per
problem). Currently we feed the LLM only the slow source code. Adding the
problem statement lets the model understand *what the program is supposed
to do* before attempting to optimise it.

**Why it helps.** Directly attacks failures like `pie_p02695_s405258011`
(persistent "deep algorithmic confusion" across all 3 modes, all 3 seeds),
where the model needs to understand the combinatorial structure of the
problem before it can avoid the materialisation bottleneck. Currently the
model has to reverse-engineer the algorithmic intent from variable names
and control flow — a lot of cognitive load that the problem statement
collapses for free.

**Implementation sketch.**
- Unzip and parse the HTML into plain text once, cache as a dict
  `{problem_id: statement}` in `data/pie_loader.py`.
- Add a new field `problem_statement` to each PIE sample.
- Inject as the very first feedback block in all three modes, before
  the source code: `=== Problem Statement === ...`.
- Truncate to ~2000 tokens to stay within the model's context.

**Cost.** ~150 lines of code; ~one afternoon. No model retraining.

**Risks / caveats.**
- Statements are translated by GPT-4 from Japanese (per PIE README) — some
  may be unclear. Sample some manually first.
- May push past the model's effective context (Qwen2.5-Coder-7B has 32K
  but quality degrades earlier).

**Related code.** `data/pie_loader.py`, `local_llm.py`/`llm_agent.py`
`_build_messages` (or `_build_user_message`).

---

### 2. In-context examples via nearest-neighbour retrieval (k-NN few-shot)

**Idea.** For each input slow code, retrieve the 2–3 most similar
`(slow → fast)` pairs from PIE's *training* split (88,136 pairs) using
code-embedding similarity. Include their diffs as in-context examples in
the prompt: "Here's how three similar programs were optimised; now do the
same for this one."

**Why it helps.** Teaches the model what *idiomatic* PIE-style
optimisations look like (replacing `std::list` with `std::vector`,
swapping `cin/cout` for `scanf/printf`, adding `ios_base::sync_with_stdio`,
etc.) without retraining. The 7B model has weak priors about competitive-
programming idioms; retrieval supplies them at inference time.

**Implementation sketch.**
- Embed every training-split slow code once using a small code embedding
  model (e.g. `BAAI/bge-code-en-v1.5` or `microsoft/unixcoder-base`).
- Build a FAISS index over the embeddings.
- At inference time, embed the test-sample slow code, retrieve top-k by
  cosine similarity, attach their diffs (already provided in PIE's `diff`
  field) to the prompt.
- Filter to retrievals from *different problems* to avoid leakage.

**Cost.** ~1 day for the embedding + index pipeline. ~10 GB disk for the
embedding cache. Inference cost: negligible.

**Risks / caveats.**
- Risk of retrieval contamination if the test split's problems also appear
  in training (PIE's splits are problem-disjoint per the README — verify).
- The KNN'd diffs might steer the model toward stylistic mimicry instead
  of correctness — pair with self-repair to catch.

**Related code.** New `tools/build_knn_index.py`; modifications in
`data/pie_loader.py` to attach retrievals.

---

### 3. Code-execution-in-the-loop (agentic)

**Idea.** Give the LLM a `run_test_case(code, input)` tool. Inside a single
turn, the model produces a candidate, calls the tool, sees the actual
output, reasons about the gap, and submits a revised candidate. Iterative,
model-controlled debugging.

**Why it helps.** Current self-repair is a fixed loop (failure → augmented
prompt → retry). With tool use, the *model* decides when to inspect, which
test case to probe, and what to change. Much closer to how a human
programmer iterates. Particularly addresses the "model doesn't know which
of N possible fixes to try" failure mode (e.g. `pie_p02714` where dynamic
mode kept producing wrong-output rewrites — given execution access, the
model could test its hypothesis cheaply and iterate).

**Implementation sketch.**
- Use HuggingFace `transformers` tool-calling support or roll a simple
  Reasoning + Acting (ReAct) prompt template.
- Tool: a small Python wrapper that calls
  `compile_and_run_tests(candidate_code, test_cases=[chosen_test])` and
  returns `{compiled, output, expected, passed, elapsed_ms}`.
- Cap iterations per sample (e.g. 5) to bound wall-clock.

**Cost.** ~2 days. Per-sample wall-clock grows 2–5×.

**Risks / caveats.**
- Tool-calling support in Qwen2.5-Coder-7B is OK but not great. A bigger
  model would do this much better.
- Need to sandbox the tool execution (we already do via subprocess —
  reuse the existing `compile_and_run_tests`).

**Related code.** New `agent.py` with the tool wrapper and the ReAct loop;
modifications to `local_llm.py` to support multi-turn generation.

---

### 4. Critic-then-revise (single-model self-critique)

**Idea.** Three LLM calls per candidate instead of one:
1. **Generator**: produce an optimised candidate.
2. **Critic**: "Review this code. Does it preserve the original behaviour
   on every test case? List any edge cases that might break."
3. **Reviser**: incorporate the critic's concerns.

Same model plays all three roles via different system prompts.

**Why it helps.** Explicitly forces the "preserve correctness" check that
the current optimize prompt skips. Addresses the v2/v3 regression where
the more-aggressive prompt produces faster but wrong code (the
correctness-vs-ambition tradeoff we documented in reflection.md §7.5).

**Implementation sketch.**
- Add `--critique-rounds N` CLI flag (default 0).
- After each generation, build a critic prompt that pairs `(original, candidate)`
  and asks "is this safe?". If critic flags issues, run the reviser.
- Persist `critique_history` per candidate in the JSONL.

**Cost.** ~1 day. Inference cost: 3× current per candidate.

**Risks / caveats.**
- Critic-reviser loops can be sycophantic (critic invents concerns,
  reviser introduces bugs to address them). Constrain the critic prompt
  to "only flag concrete edge cases, don't rewrite".
- Combine with k=3 sampling: critic-revised version becomes one of the k
  candidates, not a replacement.

**Related code.** New `format_critique_feedback` in `profiler.py`; a
`_critique_round` helper in `pipeline.py` parallel to `_self_repair_round`.

---

### 5. Constrained / grammar-aware decoding

**Idea.** Force the LLM's generation to produce syntactically valid C++
by constraining its output at decode time, using a context-free grammar
constraint via the `outlines` library or `transformers`'
`prefix_allowed_tokens_fn`.

**Why it helps.** Eliminates the `failure_mode: compile` category entirely
by construction. In our recent runs that's 1–3 failures per mode per
seed — modest but free if it works.

**Implementation sketch.**
- Define a coarse C++ CFG (or use `outlines.Cfg` with a published grammar
  from `tree-sitter-cpp`).
- Wrap the model's `generate` call with `prefix_allowed_tokens_fn` that
  enforces the grammar incrementally.
- Verify on a few samples that output is still semantically interesting
  (not just empty `int main(){}`).

**Cost.** ~2 days. Decoding becomes slower (per-token grammar mask is not
free; typically 1.5–3× wall-clock).

**Risks / caveats.**
- Strict grammar might block valid macros, GCC extensions, `using namespace
  std`-dependent code.
- Doesn't help with `wrong_output` failures (the dominant category for
  dynamic/profiling modes).

**Related code.** `local_llm.py` `repair()` function — wrap `_model.generate`.

---

## Medium-leverage

Worth trying once the high-leverage items are landed.

### 6. Process reward / intermediate signals

**Idea.** Score candidates by intermediate compile/run signals (compiles
→ runs → passes test 1 → passes all → faster) rather than only final
pass/fail. Use to early-prune the obvious losers and reallocate the eval
budget toward promising candidates.

**Why it helps.** With k=10 sampling, evaluating every candidate is
expensive (compile + run × all test cases × multiple trials). A fast
"will this compile?" gate kills compile-error candidates in <1 s, freeing
budget for the candidates that might actually win.

**Implementation sketch.**
- Add a `_quick_check(code)` that just compiles (no run).
- In `_eval_candidates`, sort candidates by quick-check result first.
- For k>5, only fully-evaluate the top N that passed quick-check.

**Cost.** Half a day. Small wall-clock savings; reallocates budget upward.

---

### 7. Self-consistency at the algorithm level

**Idea.** Generate 10 candidates with sampling, cluster them by AST
similarity or by output-on-random-test similarity, vote on the dominant
cluster. Pick the centroid of the largest correct cluster as the winner.

**Why it helps.** Currently `_select_winner` picks "the fastest correct
candidate". That's brittle to single-seed luck. If 5/10 sampled candidates
all converge on the same algorithm, that's much stronger evidence of
correctness than "1/10 happens to pass the public tests" — addresses the
"max speedup is mostly variance" finding in reflection.md §7.6.

**Implementation sketch.**
- After candidates are evaluated, compute pairwise similarity via
  `tree-sitter-cpp` AST kernels or Jaccard on tokens.
- Cluster (single-linkage at a threshold).
- Winner = first correct candidate in the largest cluster.

**Cost.** ~2 days. Inference cost unchanged; small CPU overhead.

---

### 8. Diverse beam search instead of top-p sampling

**Idea.** Replace `do_sample=True, top_p=0.95` with HuggingFace's
`num_beams=k, num_beam_groups=k, diversity_penalty=...`. Forces candidates
to differ algorithmically rather than just stylistically.

**Why it helps.** At k=3 we currently see 2–3 candidates that look very
similar (same algorithm, different identifier names). Diverse beam search
makes the k candidates explore different algorithmic branches — gives
sampling more headroom to find big wins.

**Implementation sketch.**
- Add `--decode-strategy {sample,diverse_beam}` to CLI.
- In `local_llm.py`, dispatch on this flag.

**Cost.** Half a day. Inference cost roughly the same.

**Risks / caveats.**
- Diverse beam search can produce repetitive / unnatural code. Needs
  tuning of `diversity_penalty`.

---

### 9. Static-analysis feedback channel

**Idea.** Run `clang-tidy` (or `cppcheck`) on each candidate before
executing. Inject warnings into the repair feedback: "candidate has
warning: signed-unsigned comparison at line 14, possible UB."

**Why it helps.** Catches a class of bugs that *might* pass our limited
public tests but break on edge inputs (signed overflow, missing null
terminator, off-by-one with size_t). Complements the test-driven
correctness check.

**Implementation sketch.**
- Add `_run_static_analysis(code)` that calls `clang-tidy
  --checks=*` and parses output.
- Surface warnings in `format_self_repair_feedback` for `wrong_output`
  failures.

**Cost.** ~1 day. Per-candidate wall-clock +1 s for clang-tidy.

---

## Architectural

Larger investments with possible high payoff but harder to attribute.

### 10. Two-model setup (reasoning + coding)

**Idea.** A strong reasoning model (Claude, GPT-4) plans the optimisation
strategy ("we should replace the `std::list` with `std::vector` and
remove the redundant `at()` calls"). A code-tuned local model (Qwen-7B)
implements it.

**Why it helps.** Decouples *knowing what to do* (reasoning task) from
*correctly typing the C++* (code task). The 7B model is decent at the
latter and bad at the former; offloading planning to a stronger model
should lift correctness substantially.

**Implementation sketch.**
- Use the Anthropic API (we have the backend already) to call Claude
  for the plan.
- Pass the plan as additional feedback to the local model.

**Cost.** ~1 day. Anthropic API cost ~$0.01–0.05 per sample.

**Risks / caveats.**
- Mixes API-bound and local inference; complicates the experimental
  setup.

---

### 11. Memory of past failures

**Idea.** Keep a per-failure-mode "lessons" log that accumulates across
runs. Example: "Pattern: when global variable is named `data`, watch for
collision with `std::data` (C++17)." Inject the relevant lessons into the
prompt for future runs.

**Why it helps.** Compound learning across runs. The pipeline currently
forgets every failure as soon as a run ends; each new run repeats the
same mistakes (compile error from `data` global, std::list materialisation
trap).

**Implementation sketch.**
- After each run, scan `repair_history` for systematic failures.
- Bucket them by pattern (regex on `compile_error` text, by
  `failure_mode`, etc.).
- Maintain `lessons.jsonl` with the top N lessons.
- Inject relevant lessons (matched on the input source) into the prompt.

**Cost.** ~3 days. Slow to bootstrap; compounds.

**Risks / caveats.**
- Could overfit to specific samples — generalise carefully.

---

### 12. Profile-Guided Optimization (PGO) at compile time

**Idea.** Compile slow code with `-fprofile-generate`, run it, then
recompile with `-fprofile-use`. Typically delivers 10–30 % speedup for
free, before any LLM involvement.

**Why it helps.** Makes the baseline more honest. Currently we benchmark
LLM output against `-O2 -g -pg` slow code. With PGO the slow code already
captures the compiler-level wins, so the LLM's reported speedup reflects
its *algorithmic* contribution rather than free compiler magic the human
just hadn't enabled.

**Implementation sketch.**
- Add an optional `compile_pgo` flag in `compiler.py`.
- Two-phase compile: profile-generate → run → profile-use.
- Apply to baseline timing only (so PGO improves the slow code, raising
  the bar for the LLM).

**Cost.** ~1 day. Doubles baseline compile time.

**Risks / caveats.**
- Might shrink reported speedups (= harder positive results to report).
  But more honest.

---

## Dataset side (cheapest correctness lift)

### 13. Use PIE's generated alphacode test cases

**Idea.** PIE publishes a separate bundle of generated test cases
(sourced from AlphaCode) — typically 100+ tests per problem vs the 1–8
public tests we currently use. Download link is in `pie-perf/README.md`.

**Why it helps.** Catches wrong-output failures that currently slip
through the small public test set. Specifically, samples like `p02714`
where the dynamic-mode rewrite passes the 1 public test by luck but
fails on edge cases — with 100+ tests, that rewrite would be correctly
flagged as wrong. **The single biggest lever for the credibility of our
correctness numbers.**

**Implementation sketch.**
- Download `https://drive.google.com/file/d/1migwX4wpED0gDDxn7gS6q55vWeXIDgId/view`
  (URL from `pie-perf/README.md`).
- Extract into `pie-perf/data/generated_test_cases/<problem_id>/`.
- Modify `data/pie_loader.py:_load_test_cases` to merge public + generated
  tests.
- Re-run the n=30 cputime≥100 ablation; expect correctness numbers to
  drop slightly (more tests = more failures caught) but become honest.

**Cost.** ~half a day (mostly waiting on the download). No code beyond
the loader change.

**Risks / caveats.**
- Will tighten correctness numbers downward — the existing 80% might
  become 60%. This is honest, not a regression.
- Slightly slower per-sample evaluation (more test cases = more compile-
  and-run cycles).

---

## What I'd actually do, in priority order

If picking the next single thing to work on:

1. **#13 (more test cases)** — fixes the credibility of everything else
   we've already measured. Cheapest by far.
2. **#1 (problem statements in prompt)** — biggest likely correctness lift
   on hard samples (e.g. `p02695`). Fully reuses existing infrastructure.
3. **#3 (code-execution-in-the-loop)** — biggest likely speedup lift,
   especially on samples where current iterate-on-speedup is just blind
   retry.
4. **#4 (critic-then-revise)** — fairness gate for the new aggressive
   prompt's correctness regression (reflection.md §7.5).
5. **#2 (k-NN few-shot)** — most novel research contribution; takes
   longer to wire up but produces unique signal.

Everything below this in the list is interesting but should wait until
the top five are explored.