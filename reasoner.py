"""
Reasoning agent for the optimisation pipeline.

Applies the "reason before generating" idea: before asking the optimiser-LLM
to rewrite a slow C++ program, ask the SAME local LLM to first produce a
structured Optimization Plan from all the signals the pipeline has collected
(problem statement, classifier tag, predicted complexity, runtime diff,
profile summary). That plan is then injected into the optimiser's prompt as
an extra section, so the optimiser sees explicit hypotheses about WHAT to
change instead of having to infer them from raw evidence.

Design choices:
  - Mode-aware. Each mode (static / dynamic / profiling) only sees the
    signals it is allowed to see, so the ablation stays clean.
  - Per-(mode, reasoner_id) disk cache. Reasoning is the most expensive LLM
    call in the pipeline (≈ 400 tokens out + a heavy prompt in), so we never
    pay it twice for the same (sample, mode).
  - Same model as the optimiser (Qwen2.5-Coder-7B-Instruct by default) via
    `local_llm.quick_inference`. Cheaper and avoids dragging in an extra
    backend.

Public API:
    plan_info = reason(sample_id, source, mode, ...) -> {
        "plan": "...",                # the prompt-ready Optimization Plan
        "raw":  "...",                # full LLM output (for audit)
        "reasoner_id": "qwen7b_v1",
        "cached": bool,
    }
    block = format_reasoning_block(plan)   # "Optimization Plan:\n  1) ..."
"""
import csv
import os
import sys
from typing import Optional, Callable

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# Reasoning prompt v1 — kept for audit; current default is v2 below.
_REASONING_PROMPT_V1 = """You are an expert C++ performance engineer. Your job is NOT to write code yet.
Your job is to reason about a slow C++ program and produce a concrete
optimisation plan that a separate code-generation step will then implement.

Use ONLY the evidence below. Do not invent facts.

{signals_block}

Slow C++ program to be optimised:
```cpp
{code}
```

Think step by step:
1. Identify the most likely BOTTLENECK (which loop, data structure, recursion,
   or library call is responsible for most of the runtime). Use the profile
   evidence above if present; otherwise infer from the code's algorithmic
   shape and the predicted complexity.
2. Decide what ALGORITHMIC OR STRUCTURAL CHANGE could remove that bottleneck
   while preserving identical observable behaviour for every test case
   permitted by the constraints.
3. Note any TRAPS (constant-factor tricks that won't help, transformations
   that would change observable output, edge cases the slow code handles
   that a naive rewrite might miss).

Output ONLY the plan, in the exact format below. No prose outside the tags.

<plan>
Bottleneck: <one sentence — what is slow and why>
Strategy:   <one sentence — what algorithmic/structural change removes it>
Steps:
  1) <concrete step>
  2) <concrete step>
  3) <concrete step>
Traps:      <one sentence — what to be careful about, or "none">
</plan>
"""


# Reasoning prompt v2 — biases toward CORRECTNESS-preserving changes.
# v1's "Strategy + Steps" framing made the model prescribe full algorithmic
# rewrites (queue→priority queue, nested loops→bitmask DP, etc.). A 7B model
# implementing those from a one-paragraph spec mis-handles invariants and
# regresses correctness. v2 fixes this with two structural changes:
#   (A) Pre-condition: state up-front that the slow program is ALREADY
#       Accepted, so the plan must preserve every observable behaviour.
#   (B) Preference ladder: three tiers (cheap / medium / algorithmic) with
#       an explicit gate on the third — algorithmic rewrites only when v0
#       provably cannot meet the constraints. This frontloads the cheap
#       wins (sync_with_stdio, '\n' over endl, vector::reserve) that 7B
#       models implement reliably.
_REASONING_PROMPT_V2 = """You are an expert C++ performance engineer. Your job is NOT to write code yet.
Your job is to reason about a slow C++ program and produce a concrete
optimisation plan that a separate code-generation step will then implement.

CRITICAL PRE-CONDITION: the program below is ALREADY CORRECT — it was accepted
by the online judge on every test case. It is merely SLOW. Therefore your
plan MUST preserve every observable behaviour exactly: identical stdout for
every legal input, identical edge-case handling, identical I/O ordering.
Optimisations that change the algorithm are HIGH RISK and frequently break
correctness when implemented by a smaller model. Prefer the cheapest safe
change that addresses the bottleneck.

Use ONLY the evidence below. Do not invent facts about the problem.

{signals_block}

Slow but CORRECT C++ program:
```cpp
{code}
```

Think step by step, then fill the three tiers below in order of increasing
risk. The downstream code generator will be told to prefer the lowest-risk
tier that addresses the bottleneck. Leave a tier blank ("n/a") if it does
not apply.

Tier 1 — CHEAPEST SAFE CHANGES (constant-factor; near-zero correctness risk):
  Examples: ios_base::sync_with_stdio(false); cin.tie(nullptr); '\\n' instead
  of endl; reserve()/resize() on vectors; pass-by-const-reference; replace
  printf/scanf bottlenecks; cache repeated subexpressions; switch
  std::map → std::unordered_map IFF iteration order is not observed.

Tier 2 — STRUCTURAL CHANGES (preserve algorithm shape; modest risk):
  Examples: change a 2D vector to a flat array; shrink a DP table dimension
  the constraints permit; replace a recursive call with the equivalent
  iterative loop; move an invariant computation out of a loop.

Tier 3 — ALGORITHMIC REWRITE (only if Tier 1 + Tier 2 are clearly
  insufficient given the constraints):
  Only propose this if the slow algorithm's complexity, applied to the
  problem's stated upper bounds, would NOT fit within typical contest
  limits — otherwise leave "n/a". Be specific about which invariants of
  the original algorithm the rewrite must preserve.

Output ONLY the plan, in the exact format below. No prose outside the tags.

<plan>
Bottleneck: <one sentence — what is slow and why>
Tier 1:     <one short line, or "n/a">
Tier 2:     <one short line, or "n/a">
Tier 3:     <one short line, or "n/a">
Traps:      <one sentence — invariants the rewrite MUST preserve, or "none">
</plan>
"""


# How much per-signal text to keep. The reasoner's prompt budget is
# dominated by the source code; we trim the other signals to keep the
# total prompt well under the model's window even on long samples.
_MAX_STMT_CHARS    = 1500
_MAX_PROFILE_CHARS = 1200
_MAX_RUNTIME_CHARS = 600
_MAX_CODE_CHARS    = 4000


def _truncate(s: str, n: int) -> str:
    if not s:
        return ""
    s = s.strip()
    return s if len(s) <= n else s[:n].rstrip() + "\n[... truncated]"


def _build_signals_block(problem_statement: Optional[str],
                         problem_tag: Optional[str],
                         complexity_label: Optional[str],
                         profile_summary: Optional[str],
                         runtime_feedback: Optional[str]) -> str:
    """Assemble the 'Evidence' block in a stable order."""
    parts = ["Evidence available to you:"]
    if problem_statement:
        parts.append("[Problem statement / constraints]\n"
                     + _truncate(problem_statement, _MAX_STMT_CHARS))
    if problem_tag:
        parts.append(f"[Problem classifier tag] {problem_tag}")
    if complexity_label and complexity_label != "unknown":
        parts.append(f"[Predicted complexity of the slow program] {complexity_label}")
    if runtime_feedback:
        parts.append("[Runtime evidence — expected vs actual stdout diff]\n"
                     + _truncate(runtime_feedback, _MAX_RUNTIME_CHARS))
    if profile_summary:
        parts.append("[Profiler evidence — gprof / perf / gcov summary]\n"
                     + _truncate(profile_summary, _MAX_PROFILE_CHARS))
    if len(parts) == 1:
        parts.append("(no auxiliary evidence — reason from the source code "
                     "structure alone)")
    return "\n\n".join(parts)


def _extract_plan(raw: str) -> str:
    """
    Pull the <plan>...</plan> block. If the model emitted plain text without
    tags (e.g. truncated mid-thought), return whatever sits between
    'Bottleneck:' and the end. Last resort: return the raw output trimmed.
    """
    if not raw:
        return ""
    import re
    m = re.search(r"<plan>\s*(.*?)\s*</plan>", raw, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"(Bottleneck\s*:.*)", raw, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return raw.strip()


def format_reasoning_block(plan: str) -> str:
    """
    Wrap an extracted plan into a prompt-ready section for the optimiser.

    The wrapper text is deliberately conservative: it tells the optimiser
    the plan is a HYPOTHESIS, and that it should prefer the lowest-risk
    tier that addresses the bottleneck. This counteracts the failure mode
    where v1's plans pushed the 7B optimiser into algorithmic rewrites
    that regressed correctness.
    """
    if not plan or not plan.strip():
        return ""
    return (
        "Optimization Plan (hypothesis from a separate reasoning pass; "
        "the slow program is ALREADY correct, so preserving observable "
        "behaviour outranks every speedup):\n"
        f"{plan.strip()}\n\n"
        "How to apply the plan:\n"
        "  - PREFER Tier 1 fixes (constant-factor I/O, container, and "
        "compiler hints) — these are almost always safe.\n"
        "  - If Tier 1 alone is unlikely to be enough, also apply Tier 2 "
        "(structural changes that keep the algorithm shape).\n"
        "  - Only apply Tier 3 (algorithmic rewrite) if both lower tiers "
        "are clearly inadequate; rewrites at this scale frequently "
        "introduce bugs in I/O ordering, edge cases, and tie-breaking.\n"
        "  - If any tier conflicts with preserving identical stdout, "
        "drop that tier and rely on the safer ones."
    )


# ─── Disk cache (one CSV per (mode, reasoner_id)) ───────────────────────────

def _cache_path(mode: str, reasoner_id: str) -> str:
    return os.path.join(_HERE, "data", f"reasoning_{mode}_{reasoner_id}.csv")


def _load_cache(path: str) -> dict:
    cache = {}
    if not os.path.exists(path):
        return cache
    with open(path, newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0 and row and row[0] == "sample_id":
                continue
            if len(row) >= 2:
                cache[row[0]] = row[1]
    return cache


def _append_cache(path: str, sample_id: str, plan: str):
    is_new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["sample_id", "plan"])
        w.writerow([sample_id, plan])


_inmem_cache = {}    # {(mode, reasoner_id): {sample_id: plan}}


def _local_reason_fn(prompt: str, max_new_tokens: int = 384) -> str:
    """Default reasoner: low-temperature Qwen call via local_llm."""
    from local_llm import quick_inference
    return quick_inference(prompt, max_new_tokens=max_new_tokens)


# v2 plan has more tiers but each line is shorter, so 384 tokens still
# leaves headroom for a chat-tuned preamble before the <plan> tags.
_DEFAULT_PROMPT = _REASONING_PROMPT_V2


def reason(sample_id: str,
           source: str,
           mode: str,
           *,
           problem_statement: Optional[str] = None,
           problem_tag: Optional[str] = None,
           complexity_label: Optional[str] = None,
           profile_summary: Optional[str] = None,
           runtime_feedback: Optional[str] = None,
           reasoner_id: str = "qwen7b_v2",
           reasoner_fn: Optional[Callable[[str], str]] = None,
           ) -> dict:
    """
    Produce an optimisation plan for `source` using the named evidence.

    `mode` is one of "static" / "dynamic" / "profiling" — used to key the
    disk cache so reasoning produced under different evidence regimes does
    not get conflated.

    Returns {"plan": str, "raw": str, "reasoner_id": str, "cached": bool}.
    On any failure the plan is the empty string and `cached` is False;
    callers should treat an empty plan as "no reasoning available".
    """
    if mode not in ("static", "dynamic", "profiling"):
        raise ValueError(f"Unknown reasoner mode: {mode!r}")

    path = _cache_path(mode, reasoner_id)
    cache = _inmem_cache.setdefault((mode, reasoner_id), _load_cache(path))
    if sample_id in cache:
        return {"plan": cache[sample_id], "raw": cache[sample_id],
                "reasoner_id": reasoner_id, "cached": True}

    if not source or not source.strip():
        return {"plan": "", "raw": "", "reasoner_id": reasoner_id,
                "cached": False}

    signals = _build_signals_block(problem_statement, problem_tag,
                                    complexity_label, profile_summary,
                                    runtime_feedback)
    prompt = _DEFAULT_PROMPT.format(signals_block=signals,
                                      code=_truncate(source, _MAX_CODE_CHARS))
    fn = reasoner_fn or _local_reason_fn
    try:
        raw = fn(prompt)
    except Exception as e:
        print(f"[reason] {sample_id} ({mode}) failed: {e}")
        return {"plan": "", "raw": "", "reasoner_id": reasoner_id,
                "cached": False}

    plan = _extract_plan(raw)
    # Persist even when extraction is partial — having something is better
    # than re-paying the call. If you want a strict "no garbage" cache, add
    # a heuristic gate here (e.g. require the literal "Bottleneck:" string).
    cache[sample_id] = plan
    _append_cache(path, sample_id, plan)
    return {"plan": plan, "raw": raw, "reasoner_id": reasoner_id,
            "cached": False}


def get_cache(mode: str, reasoner_id: str = "qwen7b_v2") -> dict:
    return _load_cache(_cache_path(mode, reasoner_id))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="static",
                    choices=["static", "dynamic", "profiling"])
    ap.add_argument("--source-file", required=True)
    ap.add_argument("--sample-id", default=None)
    ap.add_argument("--problem-statement", default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--complexity", default=None)
    ap.add_argument("--profile-summary", default=None)
    ap.add_argument("--runtime-feedback", default=None)
    args = ap.parse_args()

    src = open(args.source_file).read()
    sid = args.sample_id or os.path.splitext(os.path.basename(args.source_file))[0]
    info = reason(
        sid, src, args.mode,
        problem_statement=args.problem_statement,
        problem_tag=args.tag,
        complexity_label=args.complexity,
        profile_summary=(open(args.profile_summary).read()
                         if args.profile_summary else None),
        runtime_feedback=(open(args.runtime_feedback).read()
                          if args.runtime_feedback else None),
    )
    print(f"=== plan for {sid} ({args.mode}, cached={info['cached']}) ===")
    print(info["plan"])
