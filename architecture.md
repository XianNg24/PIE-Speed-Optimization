# Agentic Pipeline — Architecture

Design doc for the agentic refactor of the PIE optimisation pipeline. Build is
**incremental and additive**: nothing in this doc removes existing capability,
and the legacy flow stays the default until each agentic phase is validated
against an A/B baseline.

---

## 0. Why agentic at all

`reflection.md` and `results/run_20260616-165542_threetier/error_report.md`
established the following pattern:

1. Even the three-tier reasoner v2 (which avoided 48/49 algorithmic rewrites)
   still produces failures because Qwen-7B mis-implements *conservative*
   plans — DP table reshapes, memoisation tables with a missing state
   dimension, container swaps with broken tie-breaking.
2. A small fraction (~4%) of failures come from plans that are themselves
   wrong (counting sort with values up to 10⁹; mis-applied modular identity).
3. The existing self-repair loop bounces raw stdout diff back to the
   optimiser. There is no structured *diagnosis* of what went wrong, so the
   model frequently re-makes the same class of mistake.
4. The mutate-on-pass branch (`--iterate-speedup-rounds`) exists but is
   unconditional and uninformed by failure history.

An explicit multi-agent loop with a **Critic** between failure and re-plan
gives us:
- A named class for each failure ("off-by-one in DP base case",
  "tie-break inverted"), which can be cached and re-used across runs.
- A short-term memory of the per-sample trajectory that Planner can read on
  re-plan.
- A long-term memory of `(tag, transformation) → distilled lesson` mappings
  fed into the *initial* Planner prompt — directly addressing the recurring
  failure classes from the error report.

---

## 1. Agents

Lean named-function design. Each agent is a pure function over a shared
`AgentState`. The orchestrator decides which one runs next.

| Agent | LLM? | Input | Output | Status (this PR) |
|---|---|---|---|---|
| **Planner** | yes | `v0`, problem stmt, tag, complexity, profile, memory hits, optional critic note | three-tier plan + self-rated confidence | Reuses [reasoner.py](reasoner.py) (v2 three-tier prompt); confidence rating added later |
| **Coder** | yes | `v0`, plan, prior critic note | candidate C++ | Reuses `local_llm.repair` (existing 3 mode wrappers) |
| **Critic** | yes | failed candidate, expected vs actual stdout, prev plan, (optional) v0 source | `{failure_class, evidence, replacement_block, plan_was_wrong}` | shipped (v2: emits a code patch, not free-text; uses delta-debug input shrinker when v0 is available); see [agent_critic.py](agent_critic.py) |
| **Verifier** | no | candidate src | compile + run + speedup verdict | Reuses `compiler.compile_and_run_tests` |
| **ProfileReader** | no | binary, test inputs | gprof/perf/gcov summary block | Reuses `profiler.profile` |
| **Mutator** | yes | passing candidate, current speedup | strictly-faster mutation | Reuses `iterate-on-speedup` block (later phase) |

---

## 2. Tools

Deterministic operations the agents call. All exist already; the agentic
refactor just wraps them as `(name, signature)` for orchestrator dispatch.

| Tool | Signature | Backing |
|---|---|---|
| `compile` | `(src) → {ok, errors}` | `compiler.compile_cpp` |
| `run` | `(bin, stdin, timeout) → {stdout, returncode, time}` | `compiler.run_binary` |
| `profile` | `(bin, stdin) → {gprof, perf, gcov}` | `profiler.profile` |
| `diff` | `(actual, expected) → {first_diverging_offset, line_diff}` | tiny helper in `agent_critic.py` |
| `shrink_failing_input` | `(v0_bin, candidate_bin, failing_stdin) → (shrunk_stdin, v0_out, cand_out)` | shipped in `agent_critic.py` (line-based delta-debug bounded by 8 iterations; runs v0 as oracle for sub-inputs) |
| `constraints` | `(problem_id) → bounds` | `data.pie_loader.get_problem_statement` + a regex (Phase 2) |
| `lookup_memory` | `(tag, xform) → [lessons]` | `data/agent_memory.jsonl` (Phase 2) |

---

## 3. Memory

Two layers, with distinct lifetimes.

### 3.1 Short-term — per-sample trajectory

Lives on the `AgentState` for the current `(sample, mode)`. A `list[Attempt]`
where each `Attempt` carries `(plan, candidate_diff, verdict, critic_note)`.
Serialised to `samples/<id>/agent_trace_<mode>.json` for offline inspection.

Read by: Planner (on re-plan) and Critic (so it can see what was tried before).

### 3.2 Long-term — `(tag, transformation) → lesson`

Cross-sample, cross-run. Distilled from Critic outputs across past runs;
keyed by `(problem_tag, transformation_class)`. Storage: append-only JSONL at
`data/agent_memory.jsonl`. Bootstrapped from the existing 49 failures in
`run_20260616-165542_threetier`.

Read by: Planner before the *initial* plan. Injected into the prompt as a
"Common pitfalls for this kind of problem:" block.

**This PR ships only the schema and the Critic-output writer; the lookup
side (RAG into Planner prompt) is Phase 2.**

---

## 4. Orchestrator — state machine

Runs once per `(sample, mode)`. Treats the existing `k` initial candidates
as one super-attempt; the Critic + re-plan logic activates only when all `k`
fail.

```
                       ┌────────────┐
                       │   START    │
                       └─────┬──────┘
                             │
            ┌────────────────▼─────────────────┐
            │  Gather signals (mode-aware):    │
            │  - problem statement, tag,       │
            │  - complexity, test cases,       │
            │  - profile summary (if profiling)│
            └────────────────┬─────────────────┘
                             ▼
                       Planner (initial)
                             │
                             ▼
                       Coder (k candidates)
                             │
                             ▼
                       Verifier (all k)
                             │
                ┌────────────┴────────────┐
                ▼                         ▼
        any candidate passed?        all failed?
                │                         │
                ▼                         ▼
        (passed branch)             Critic on least-bad
                │                         │
                ▼                         ▼
        mutate_budget > 0 ?         repair_budget > 0 ?
            yes   no                    yes   no
            │     │                       │    │
            ▼     ▼                       ▼    ▼
        Mutator  DONE                 Planner  ABORT
                  │                       │
                  ▼                       ▼
                Coder (k=1)             Coder (k=1)
                  │                       │
                  ▼                       ▼
                Verifier                Verifier
                  │                       │
                  └─→ (loop, bounded)    └─→ (loop, bounded)
```

Two independent budgets:
- `repair_budget` — how many Critic → re-plan → recode cycles after failure
- `mutate_budget` — how many Mutator cycles after a pass

Both default to current pipeline values (`--repair-rounds`, `--iterate-speedup-rounds`).

### Termination

Both loops are **budget-bound only**. The orchestrator deliberately does NOT
compare against oracle speedup at any point — oracle is eval-time metadata
that the model would not have in deployment, and feeding it into a loop
decision would (a) leak eval information into inference and (b) make any
"x% of oracle" report circular. Oracle appears only in `summary.txt` as a
reference column for the analyst.

| Condition | Result |
|---|---|
| Winner passes AND mutate_budget = 0 | `DONE` |
| Winner passes AND mutate_budget > 0 | enter Mutator branch, keep going until budget exhausted or a round fails to improve over the current winner |
| All candidates fail AND repair_budget = 0 | `ABORT` (record least-bad as winner, same as today) |

Within the Mutator branch, the **only** comparison is to the *previous*
winner's measured runtime — a candidate is "accepted" iff it passes all
tests AND its mean runtime beats the previous winner's. No external
threshold.

---

## 5. Mode-aware evidence (preserves the ablation)

Same isolation as the existing reasoner:

| Mode | Planner sees | Critic sees |
|---|---|---|
| static | problem stmt, tag, complexity, code | failed code, stdout diff, prev plan |
| dynamic | + runtime feedback | + runtime feedback |
| profiling | + full profile summary | + profile summary, hot lines |

The orchestrator passes only the mode-appropriate signals; no leakage.

---

## 6. File layout (this PR)

```
defects4c_project/
├── architecture.md            (THIS DOC)
├── agent_state.py             (NEW)  AgentState + Attempt dataclasses
├── agent_critic.py            (NEW)  Critic agent + disk cache
├── pipeline.py                (EDIT) --agentic flag; Critic in repair loop
├── data/
│   └── critic_qwen7b_v1.csv   (auto-created on first Critic call)
└── results/run_<ts>/samples/<id>/
    └── agent_trace_<mode>.json  (NEW per-sample artifact when --agentic on)
```

---

## 7. Integration with existing pipeline

Single switch: `--agentic` (default OFF, opt-in like `--reason`).

When OFF, the pipeline behaves exactly as today.

When ON, **only one path changes**: inside `_self_repair_round`, the bare
failure feedback is replaced with `format_self_repair_feedback(...) + critic_block`,
where `critic_block` is the Critic's structured diagnosis. The
state-machine for k initial candidates, mutate-on-pass, and per-mode
artifact persistence is untouched.

This minimal integration is intentional: it lets us A/B `--agentic` ON vs
OFF against the same seeded sample set and attribute any gain to the Critic
specifically. Larger restructure (a true orchestrator that owns the whole
loop) lands in Phase 2 once Critic is validated.

---

## 8. Phases

| Phase | Scope | Status |
|---|---|---|
| **1 (this PR)** | `AgentState` skeleton, Critic agent, Critic in repair loop, `architecture.md` | in progress |
| 2 | Pull mutate-loop into orchestrator; long-term memory lookup (RAG into Planner); plan-quality validator (catches counting-sort-with-10⁹ class of bug) | next |
| 3 | Confidence-rated plans; tag-gated Planner (skip planning on dp/graph by default); explicit budgets per problem tag | later |
| 4 | Migrate orchestrator to LangGraph if state machine outgrows hand-rolled dispatch | only if needed |

---

## 9. What this PR is NOT

- Not a rewrite of `pipeline.py`. The existing per-mode dispatch, candidate
  selection, and artifact persistence are unchanged.
- Not a new framework dependency (no LangGraph / AutoGen / CrewAI yet).
- Not a Mutator overhaul — `--iterate-speedup-rounds` keeps its current
  behaviour for now.
- Not a long-term memory query — the Critic *writes* to the long-term
  store, but the Planner does not yet *read* from it.

---

## 10. Critic changelog

### v1 → v2 (this iteration)

Run `results/run_20260623-160426` ran agentic-on for the first time. Net
effect on the 69-sample A/B vs `_threetier` baseline: 0 static fail→pass,
3 profiling fail→pass, 4 profiling pass→fail. Speedup deltas were flat
with high variance — within sampling noise. Three concrete defects in the
v1 Critic were identified from the trace artifacts and addressed in v2:

| v1 defect | v2 fix |
|---|---|
| 78% of failures labelled `wrong_state_dim` or `wrong_base_case` regardless of cause | Removed both anchor labels; replaced with 7 specific sub-classes (`wrong_loop_bound`, `wrong_initial_value`, `missing_state_dimension`, `wrong_iteration_order`, `wrong_comparator`, `index_out_of_bounds`, etc.) |
| `suggested_fix` was an abstract sentence the optimiser could not operationalise (e.g. "ensure the state dimension is properly managed") | Replaced with `replacement_block`: a literal C++ patch hunk. Format block in the next prompt presents it as "Apply this exact change to the previous code:" |
| 0 / 123 calls ever set `plan_was_wrong=true`, despite ≥ 2 documented plan-quality bugs | Prompt now lists plan-impossibility examples (counting sort with 10⁹ values, recurrence missing a state dimension) and asks plan validity *separately* from code correctness |
| Critic saw only full PIE test cases, often with multi-line inputs that obscured the failing detail | Added tool `shrink_failing_input` — line-based delta-debug against v0 (known correct). Cap 8 iterations. Output stitched into the prompt as `(delta-debugged minimal)` |
| `max_new_tokens=256` truncated some outputs before the JSON closed | Bumped to 512 to leave room for the patch |

Cache: bumped default `critic_id` to `qwen7b_v2`; existing
`data/critic_qwen7b_v1.csv` is preserved as audit trail. `_extract_diagnosis`
accepts either schema for backward compatibility.
