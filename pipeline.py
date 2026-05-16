"""
Profile-Guided Code Correction & Optimisation Pipeline.

Two datasets are supported:

  --dataset synthetic   (default) — bug-fix samples from data/bugs.py.
                                    Pass criterion: stdout matches expected.
  --dataset pie                   — performance samples from PIE (CodeNet).
                                    Pass criterion: all test cases match,
                                    AND speedup metric is reported.

Three repair / optimisation modes:
  1. static    – LLM sees only the slow / buggy code
  2. dynamic   – LLM additionally sees runtime feedback (output diff or timing)
  3. profiling – LLM additionally sees gprof flat profile + perf stat

Results are written to results/results_<model>.jsonl.
"""
import argparse
import json
import os
import statistics
import sys
import time

from config import RESULTS_DIR
from compiler import compile_and_run, compile_and_run_tests
from profiler import (
    profile, format_profile_for_llm, format_runtime_feedback,
    format_pie_runtime_feedback, format_pie_profile_for_llm,
    format_self_repair_feedback, format_iterate_speedup_feedback,
    parse_gprof_hotspots, annotate_source_with_hotspots,
    parse_gprof_top_entries,
)
from data.bugs import SAMPLES as SYNTHETIC_SAMPLES

LOCAL_DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"
ALL_MODES = ("static", "dynamic", "profiling")


# ─── Per-run artifact writers ────────────────────────────────────────────────
import difflib as _difflib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
from normalize_cpp import normalize_cpp as _normalize_cpp


def _write_text(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content if content is not None else "")


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, default=str)


def _make_unified_diff(a: str, b: str, fromfile: str, tofile: str,
                        n_context: int = 3, normalize: bool = True) -> str:
    """
    Build a unified diff between two source strings. When `normalize=True`
    (the default), both sides are passed through `normalize_cpp()` first so
    that whitespace-only differences (blank lines, trailing spaces, tabs vs
    spaces) don't pollute the diff.
    """
    if normalize:
        a = _normalize_cpp(a)
        b = _normalize_cpp(b)
    a_lines = (a or "").splitlines(keepends=True)
    b_lines = (b or "").splitlines(keepends=True)
    a_lines = [l if l.endswith("\n") else l + "\n" for l in a_lines]
    b_lines = [l if l.endswith("\n") else l + "\n" for l in b_lines]
    return "".join(_difflib.unified_diff(
        a_lines, b_lines, fromfile=fromfile, tofile=tofile, n=n_context,
    ))


def _write_diff(path, a, b, fromfile, tofile):
    diff = _make_unified_diff(a, b, fromfile, tofile)
    _write_text(path, diff if diff else "(no diff — files are identical)\n")


def _write_sample_sources(sample_dir, sample, dataset):
    """Write v0_*.cpp, v1_*.cpp, and the oracle diff between them."""
    if dataset == "pie":
        v0_path = os.path.join(sample_dir, "v0_slow.cpp")
        v1_path = os.path.join(sample_dir, "v1_fast.cpp")
        v0_name, v1_name = "v0_slow.cpp", "v1_fast.cpp"
    else:
        v0_path = os.path.join(sample_dir, "v0_buggy.cpp")
        v1_path = os.path.join(sample_dir, "v1_fixed.cpp")
        v0_name, v1_name = "v0_buggy.cpp", "v1_fixed.cpp"
    _write_text(v0_path, sample["buggy_code"])
    _write_text(v1_path, sample["fixed_code"])
    _write_diff(os.path.join(sample_dir, "oracle_v0_to_v1.diff"),
                sample["buggy_code"], sample["fixed_code"],
                fromfile=v0_name, tofile=v1_name)


def _write_profile_artifacts(sample_dir, raw_profile, slow_per_test,
                              annotated_source, user_hotspots, top_entries,
                              profiled_test_idx):
    """Write gprof/perf/hotspots artifacts when profile mode is run."""
    _write_text(os.path.join(sample_dir, "gprof_flat.txt"),
                raw_profile.get("gprof", ""))
    _write_text(os.path.join(sample_dir, "perf_stat.txt"),
                raw_profile.get("perf_stat", ""))
    _write_json(os.path.join(sample_dir, "hotspots.json"), {
        "profiled_test_idx": profiled_test_idx,
        "profiled_test_mean_ms": (slow_per_test[profiled_test_idx].get("mean_ms")
                                  if slow_per_test else None),
        "user_function_hotspots": user_hotspots,
        "top_gprof_entries": top_entries,
    })
    _write_text(os.path.join(sample_dir, "annotated_source.cpp"),
                annotated_source or "")


def _write_mode_candidates(sample_dir, mode_name, candidate_runs, mode_result,
                            original_code: str = None,
                            original_name: str = "v0_slow.cpp"):
    """
    Write per-candidate code + run result + diff-vs-original, plus mode summary.
    `original_code` is the slow/buggy source the LLM was asked to transform.
    """
    mode_dir = os.path.join(sample_dir, mode_name)
    for i, c in enumerate(candidate_runs):
        cand_path = os.path.join(mode_dir, f"candidate_{i}.cpp")
        _write_text(cand_path, c["fixed_code"])
        if original_code is not None:
            _write_diff(os.path.join(mode_dir, f"candidate_{i}_vs_v0.diff"),
                        original_code, c["fixed_code"],
                        fromfile=original_name,
                        tofile=f"{mode_name}/candidate_{i}.cpp")
        run = c["run"]
        _write_json(os.path.join(mode_dir, f"candidate_{i}_run.json"), {
            "passed": run["passed"],
            "compiled": run["compiled"],
            "failure_mode": run.get("failure_mode"),
            "mean_ms": run.get("mean_ms"),
            "median_ms": run.get("median_ms"),
            "per_test": run.get("per_test", []),
            "compile_error": (run.get("compile_error") or "")[:2000],
        })
    # Compact mode summary (mirrors what goes to JSONL)
    summary = {k: v for k, v in mode_result.items()
               if k not in {"fixed_code", "raw_response", "candidates"}}
    _write_json(os.path.join(mode_dir, "summary.json"), summary)
    # Also write the chosen winner's source + its diff vs original
    if mode_result.get("fixed_code"):
        _write_text(os.path.join(mode_dir, "winner.cpp"),
                    mode_result["fixed_code"])
        if original_code is not None:
            _write_diff(os.path.join(mode_dir, "winner_vs_v0.diff"),
                        original_code, mode_result["fixed_code"],
                        fromfile=original_name,
                        tofile=f"{mode_name}/winner.cpp")


def _select_winner(candidate_runs, baseline_ms):
    """
    Given a list of dicts {fixed_code, run_result}, pick the best correct
    candidate by speedup. If none correct, return the candidate that
    "least failed" (compile+ran > compile+wrong > compile+timeout > no_compile).
    Returns (winner_index, winner_candidate, pass_at_k_correct).
    """
    correct = [(i, c) for i, c in enumerate(candidate_runs) if c["run"]["passed"]]
    if correct and baseline_ms:
        i, c = max(correct,
                   key=lambda ic: (baseline_ms / ic[1]["run"]["mean_ms"])
                   if ic[1]["run"].get("mean_ms") else 0)
        return i, c, True
    if correct:
        return correct[0][0], correct[0][1], True
    # No correct candidate — pick the one with the "least bad" failure mode.
    severity = {"compile": 4, "timeout": 3, "runtime_error": 2,
                "wrong_output": 1, None: 0}
    i, c = min(enumerate(candidate_runs),
               key=lambda ic: severity.get(ic[1]["run"].get("failure_mode"), 5))
    return i, c, False


def run_sample(sample: dict, modes=ALL_MODES, verbose: bool = True,
               backend: str = "local", model_name: str = LOCAL_DEFAULT_MODEL,
               k: int = 1, temperature: float = 0.6,
               repair_rounds: int = 0, seed: int = 0,
               run_dir: str = None) -> dict:
    """
    Run one bug sample through the pipeline.
    Returns a result dict for this sample.
    """
    sid = sample["id"]
    if verbose:
        print(f"\n{'='*60}")
        print(f"Sample: {sid}")
        print(f"Bug type: {sample['bug_type']}")
        print(f"Description: {sample['description']}")
        print(f"{'='*60}")

    result = {
        "id": sid,
        "bug_type": sample["bug_type"],
        "description": sample["description"],
        "static": None,
        "dynamic": None,
        "profiling": None,
    }

    sample_dir = os.path.join(run_dir, "samples", sid) if run_dir else None
    if sample_dir:
        _write_sample_sources(sample_dir, sample, "synthetic")
        _write_json(os.path.join(sample_dir, "sample_meta.json"), {
            "id": sid,
            "bug_type": sample.get("bug_type"),
            "description": sample.get("description"),
            "expected_output": sample.get("expected_output"),
        })

    # ── 0. Verify buggy code behaviour ────────────────────────────────────────
    buggy_run = compile_and_run(
        sample["buggy_code"],
        name=f"{sid}_buggy",
        expected_output=sample["expected_output"],
    )
    if verbose:
        status = "compiled" if buggy_run["compiled"] else "COMPILE ERROR"
        print(f"[Buggy]  {status}  |  ran={buggy_run.get('ran')}  |  passed={buggy_run['passed']}")
        if not buggy_run["compiled"]:
            print("  Compile error:", buggy_run["compile_error"][:200])
    if sample_dir:
        _write_json(os.path.join(sample_dir, "baseline_run.json"), {
            "compiled": buggy_run["compiled"], "passed": buggy_run["passed"],
            "stdout": buggy_run.get("stdout", "")[:2000],
            "compile_error": (buggy_run.get("compile_error", "") or "")[:2000],
        })

    # ── 1. Build feedback blocks (if buggy compiled) ──────────────────────────
    compile_warnings = buggy_run.get("compile_error", "")
    runtime_feedback = None
    profile_summary = None
    if buggy_run["compiled"] and buggy_run.get("binary_path"):
        runtime_feedback = format_runtime_feedback(
            compile_warnings,
            actual_output=buggy_run.get("stdout", ""),
            expected_output=sample.get("expected_output", ""),
        )
        if "profiling" in modes:
            raw_profile = profile(buggy_run["binary_path"])
            profile_summary = format_profile_for_llm(
                raw_profile, compile_warnings,
                actual_output=buggy_run.get("stdout", ""),
                expected_output=sample.get("expected_output", ""),
            )
            if sample_dir:
                _write_text(os.path.join(sample_dir, "gprof_flat.txt"),
                            raw_profile.get("gprof", ""))
                _write_text(os.path.join(sample_dir, "perf_stat.txt"),
                            raw_profile.get("perf_stat", ""))
            if verbose:
                print("\n[Profile summary (first 2000 chars)]")
                print(profile_summary[:2000])

    # ── 2. Resolve repair functions ───────────────────────────────────────────
    if backend == "anthropic":
        try:
            from llm_agent import repair_static, repair_dynamic, repair_profiling
        except RuntimeError as e:
            print(f"  [LLM SKIP] {e}")
            return result
        _static_fn    = lambda code: repair_static(code, k=k, temperature=temperature, seed=seed)
        _dynamic_fn   = lambda code, fb: repair_dynamic(code, fb, k=k, temperature=temperature, seed=seed)
        _profiling_fn = lambda code, fb: repair_profiling(code, fb, k=k, temperature=temperature, seed=seed)
    else:
        from local_llm import (
            repair_static as _local_static,
            repair_dynamic as _local_dynamic,
            repair_profiling as _local_profiling,
        )
        _static_fn    = lambda code: _local_static(code, model_name=model_name, k=k, temperature=temperature, seed=seed)
        _dynamic_fn   = lambda code, fb: _local_dynamic(code, fb, model_name=model_name, k=k, temperature=temperature, seed=seed)
        _profiling_fn = lambda code, fb: _local_profiling(code, fb, model_name=model_name, k=k, temperature=temperature, seed=seed)

    # Synthetic eval helper: returns the same shape as PIE's per-test list
    # so format_self_repair_feedback can read it.
    def _failure_mode_synth(run):
        if run.get("passed"): return None
        if not run.get("compiled"): return "compile"
        if run.get("returncode") not in (0, None): return "runtime_error"
        return "wrong_output"

    def _eval_one_synth(code, name):
        r = compile_and_run(code, name=name, expected_output=sample["expected_output"])
        r["failure_mode"] = _failure_mode_synth(r)
        r["per_test"] = [{
            "idx": 0, "passed": r["passed"], "stdout": r.get("stdout", ""),
            "expected": sample["expected_output"], "failure_mode": r["failure_mode"],
        }]
        return r

    if backend == "anthropic":
        from llm_agent import repair as _repair_call
    else:
        from local_llm import repair as _repair_call

    def _self_repair_round_synth(mode_name, base_feedback, prev_winner, round_idx):
        repair_fb = format_self_repair_feedback(
            prev_winner["fixed_code"], prev_winner["run"], base_feedback,
        )
        kw = dict(mode=mode_name, model_name=model_name, k=1) \
             if backend == "local" else dict(mode=mode_name, k=1)
        new_out = _repair_call(buggy_code=sample["buggy_code"],
                               feedback=repair_fb, **kw)
        new_run = _eval_one_synth(new_out["fixed_code"],
                                  name=f"{sid}_{mode_name}_r{round_idx+1}")
        return {"fixed_code": new_out["fixed_code"], "run": new_run}

    def _run_mode(mode_name: str, fn, *args, base_feedback=None):
        if verbose:
            tag = backend if backend != "local" else model_name
            print(f"\n[{mode_name.capitalize()} mode] Calling LLM ({backend}: {tag}, k={k})...")
        t0 = time.time()
        repair_out = fn(*args)
        elapsed = time.time() - t0
        # Evaluate every candidate; pass@k = any candidate passes
        cand_runs = []
        for ci, cand in enumerate(repair_out.get("candidates",
                                                 [{"fixed_code": repair_out["fixed_code"]}])):
            r = _eval_one_synth(cand["fixed_code"], f"{sid}_{mode_name}_k{ci}")
            cand_runs.append({"fixed_code": cand["fixed_code"], "run": r})
        # Winner = first correct candidate; else first
        correct = [(i, c) for i, c in enumerate(cand_runs) if c["run"]["passed"]]
        win_idx, winner = correct[0] if correct else (0, cand_runs[0])

        # ── Self-repair retry loop ────────────────────────────────────────────
        repair_history = []
        if not correct and repair_rounds > 0:
            prev_winner = winner
            for round_idx in range(repair_rounds):
                if verbose:
                    fm = prev_winner["run"].get("failure_mode") or "?"
                    print(f"  [Self-repair round {round_idx+1}] prev_failure={fm}")
                tr = time.time()
                new_cand = _self_repair_round_synth(mode_name, base_feedback,
                                                     prev_winner, round_idx)
                round_elapsed = time.time() - tr
                cand_runs.append(new_cand)
                new_run = new_cand["run"]
                repair_history.append({
                    "round": round_idx + 1,
                    "prev_failure_mode": prev_winner["run"].get("failure_mode"),
                    "new_passed": new_run["passed"],
                    "new_failure_mode": new_run.get("failure_mode"),
                    "elapsed_s": round(round_elapsed, 2),
                })
                if verbose:
                    fm = new_run.get("failure_mode") or "ok"
                    print(f"    -> passed={new_run['passed']}  failure={fm}  "
                          f"({round_elapsed:.1f}s)")
                if new_run["passed"]:
                    win_idx = len(cand_runs) - 1
                    winner = new_cand
                    correct = [(win_idx, winner)]
                    break
                prev_winner = new_cand

        run = winner["run"]
        n_correct = sum(1 for c in cand_runs if c["run"]["passed"])
        cand_summary = [
            {"idx": i, "passed": c["run"]["passed"],
             "compiled": c["run"]["compiled"],
             "failure_mode": c["run"].get("failure_mode"),
             "from_repair": i >= k}
            for i, c in enumerate(cand_runs)
        ]
        repair_out.update({
            "elapsed_s": round(elapsed, 2),
            "winner_idx": win_idx,
            "k_correct": n_correct,
            "passed_at_k": bool(correct),
            "n_candidates_total": len(cand_runs),
            "repair_rounds_used": len(repair_history),
            "repair_history": repair_history,
            "fixed_code": winner["fixed_code"],
            "candidates_summary": cand_summary,
            "raw_response": repair_out.get("raw_response", "")[:2000],
            "compiled": run["compiled"],
            "ran": run.get("ran"),
            "passed": run["passed"],
            "stdout": run["stdout"],
            "compile_error": run.get("compile_error", ""),
        })
        if verbose:
            extra = f"  (incl. {len(repair_history)} repair rounds)" if repair_history else ""
            print(f"  k={k} correct={n_correct}/{len(cand_runs)}  pass@k={bool(correct)}  "
                  f"winner_idx={win_idx}  compiled={run['compiled']}  "
                  f"passed={run['passed']}  ({elapsed:.1f}s){extra}")
        repair_out.pop("candidates", None)
        _run_mode._last_candidate_runs = cand_runs
        return repair_out

    if "static" in modes:
        result["static"] = _run_mode("static", _static_fn,
                                     sample["buggy_code"], base_feedback=None)
        if sample_dir:
            _write_mode_candidates(sample_dir, "static",
                                   _run_mode._last_candidate_runs, result["static"],
                                   original_code=sample["buggy_code"],
                                   original_name="v0_buggy.cpp")

    if "dynamic" in modes and runtime_feedback:
        result["dynamic"] = _run_mode("dynamic", _dynamic_fn,
                                      sample["buggy_code"], runtime_feedback,
                                      base_feedback=runtime_feedback)
        if sample_dir:
            _write_mode_candidates(sample_dir, "dynamic",
                                   _run_mode._last_candidate_runs, result["dynamic"],
                                   original_code=sample["buggy_code"],
                                   original_name="v0_buggy.cpp")

    if "profiling" in modes and profile_summary:
        result["profiling"] = _run_mode("profiling", _profiling_fn,
                                        sample["buggy_code"], profile_summary,
                                        base_feedback=profile_summary)
        if sample_dir:
            _write_mode_candidates(sample_dir, "profiling",
                                   _run_mode._last_candidate_runs, result["profiling"],
                                   original_code=sample["buggy_code"],
                                   original_name="v0_buggy.cpp")

    if sample_dir:
        _write_json(os.path.join(sample_dir, "summary.json"), result)

    return result


def run_pie_sample(sample: dict, modes=ALL_MODES, verbose: bool = True,
                   backend: str = "local", model_name: str = LOCAL_DEFAULT_MODEL,
                   k: int = 1, temperature: float = 0.6,
                   repair_rounds: int = 0, seed: int = 0,
                   iterate_speedup_rounds: int = 0,
                   run_dir: str = None) -> dict:
    """
    PIE pipeline: each sample is a (slow, fast) pair plus public test cases.
    The model is asked to produce a faster correct version of the slow code.

    Pass criterion: all test cases produce correct output.
    Speedup is reported per repaired version vs. the slow baseline.
    """
    sid = sample["id"]
    if verbose:
        print(f"\n{'='*60}")
        print(f"Sample: {sid}   problem={sample['problem_id']}   "
              f"v0={sample['cpu_time_v0']}  v1={sample['cpu_time_v1']}  "
              f"+{sample['improvement_frac']:.0f}%")
        print(f"Tests: {len(sample['test_cases'])}")
        print(f"{'='*60}")

    result = {
        "id": sid,
        "source": "pie",
        "problem_id": sample["problem_id"],
        "improvement_frac_oracle": sample["improvement_frac"],
        "static": None, "dynamic": None, "profiling": None,
    }

    sample_dir = os.path.join(run_dir, "samples", sid) if run_dir else None
    if sample_dir:
        _write_sample_sources(sample_dir, sample, "pie")
        _write_json(os.path.join(sample_dir, "sample_meta.json"), {
            "id": sid,
            "problem_id": sample["problem_id"],
            "cpu_time_v0_oracle": sample["cpu_time_v0"],
            "cpu_time_v1_oracle": sample["cpu_time_v1"],
            "improvement_frac_oracle": sample["improvement_frac"],
            "n_test_cases": len(sample["test_cases"]),
        })

    # ── 0. Baseline: compile + run + time the slow version ───────────────────
    slow = compile_and_run_tests(
        sample["buggy_code"], name=f"{sid}_slow", test_cases=sample["test_cases"],
    )
    result["baseline"] = {
        "compiled": slow["compiled"], "passed": slow["passed"],
        "mean_ms": slow["mean_ms"], "median_ms": slow["median_ms"],
    }
    if verbose:
        print(f"[Slow baseline] compiled={slow['compiled']} passed={slow['passed']} "
              f"mean={slow['mean_ms']} ms")
        if not slow["compiled"]:
            print("  Compile error:", slow["compile_error"][:200])
    if sample_dir:
        _write_json(os.path.join(sample_dir, "baseline_timing.json"), {
            "compiled": slow["compiled"], "passed": slow["passed"],
            "failure_mode": slow.get("failure_mode"),
            "mean_ms": slow["mean_ms"], "median_ms": slow["median_ms"],
            "per_test": slow.get("per_test", []),
        })

    # ── 1. Build feedback blocks (need a binary; baseline can be partially failing,
    #       e.g. TLE on some tests — that itself is informative feedback). ────────
    runtime_feedback = None
    profile_summary = None
    profile_buggy_code = sample["buggy_code"]   # default: no annotations
    if slow["compiled"] and slow["binary_path"] and slow.get("per_test"):
        runtime_feedback = format_pie_runtime_feedback(slow["per_test"], slow["mean_ms"])
        if "profiling" in modes:
            # Profile against the slowest test case that didn't time out (so gprof
            # has samples). Fall back to the first test case if all timed out.
            ok_tests = [i for i, t in enumerate(slow["per_test"])
                        if not t.get("timed_out") and t.get("mean_ms") is not None]
            if ok_tests:
                slowest_idx = max(ok_tests, key=lambda i: slow["per_test"][i]["mean_ms"])
            else:
                slowest_idx = 0
            stdin_for_profile = sample["test_cases"][slowest_idx]["input"]
            if verbose:
                ms = slow["per_test"][slowest_idx].get("mean_ms")
                print(f"[Profile target] test #{slowest_idx} ({ms} ms)")
            raw_profile = profile(slow["binary_path"], stdin_data=stdin_for_profile)
            profile_summary = format_pie_profile_for_llm(
                raw_profile, slow["per_test"], slow["mean_ms"],
            )
            # Inline gprof hotspots into the source for the profile-mode prompt.
            # Falls back to a file-level header comment if no user functions match.
            gprof_str = raw_profile.get("gprof", "")
            hotspots = parse_gprof_hotspots(gprof_str)
            top_entries = parse_gprof_top_entries(gprof_str)
            profile_buggy_code = annotate_source_with_hotspots(
                sample["buggy_code"], hotspots, gprof_output=gprof_str,
            )
            if verbose:
                if hotspots and any(h["name"] in profile_buggy_code for h in hotspots[:4]):
                    names = ", ".join(f"{h['name']}({h['pct']:.0f}%)" for h in hotspots[:4])
                    print(f"[Hotspot annotations] inlined per-function: {names}")
                elif "HOTSPOT FILE-LEVEL SUMMARY" in profile_buggy_code:
                    print(f"[Hotspot annotations] file-level fallback (STL hotspots)")
            if verbose:
                print("\n[Profile summary (first 2000 chars)]")
                print(profile_summary[:2000])
            # Persist profile artifacts to disk for this sample
            if sample_dir:
                _write_profile_artifacts(
                    sample_dir, raw_profile, slow["per_test"], profile_buggy_code,
                    hotspots, top_entries, slowest_idx,
                )

    # Also persist the LLM-prompt blocks for offline inspection.
    if sample_dir:
        if runtime_feedback:
            _write_text(os.path.join(sample_dir, "prompt_runtime_feedback.txt"),
                        runtime_feedback)
        if profile_summary:
            _write_text(os.path.join(sample_dir, "prompt_profile_summary.txt"),
                        profile_summary)

    # ── 2. Resolve repair functions ──────────────────────────────────────────
    if backend == "anthropic":
        try:
            from llm_agent import repair_static, repair_dynamic, repair_profiling
        except RuntimeError as e:
            print(f"  [LLM SKIP] {e}")
            return result
        _static_fn    = lambda code: repair_static(code, k=k, temperature=temperature, seed=seed, task_type="optimize")
        _dynamic_fn   = lambda code, fb: repair_dynamic(code, fb, k=k, temperature=temperature, seed=seed, task_type="optimize")
        _profiling_fn = lambda code, fb: repair_profiling(code, fb, k=k, temperature=temperature, seed=seed, task_type="optimize")
    else:
        from local_llm import (
            repair_static as _local_static,
            repair_dynamic as _local_dynamic,
            repair_profiling as _local_profiling,
        )
        _static_fn    = lambda code: _local_static(code, model_name=model_name, k=k, temperature=temperature, seed=seed, task_type="optimize")
        _dynamic_fn   = lambda code, fb: _local_dynamic(code, fb, model_name=model_name, k=k, temperature=temperature, seed=seed, task_type="optimize")
        _profiling_fn = lambda code, fb: _local_profiling(code, fb, model_name=model_name, k=k, temperature=temperature, seed=seed, task_type="optimize")

    baseline_ms = slow["mean_ms"]

    def _eval_candidates(mode_name, repair_out, label_offset: int = 0):
        """Compile + run all k candidates, attach run results."""
        runs = []
        for ci, cand in enumerate(repair_out.get("candidates",
                                                 [{"fixed_code": repair_out["fixed_code"]}])):
            run = compile_and_run_tests(
                cand["fixed_code"],
                name=f"{sid}_{mode_name}_k{label_offset + ci}",
                test_cases=sample["test_cases"],
            )
            runs.append({
                "fixed_code": cand["fixed_code"],
                "run": run,
                "completion_tokens": cand.get("completion_tokens"),
            })
        return runs

    # Direct underlying repair() so we can pass an arbitrary feedback string
    # for self-repair (mode-agnostic).
    if backend == "anthropic":
        from llm_agent import repair as _repair_call
    else:
        from local_llm import repair as _repair_call

    def _self_repair_round(mode_name, base_feedback, prev_winner, round_idx):
        """Single self-repair round. Returns the new candidate's run dict."""
        repair_fb = format_self_repair_feedback(
            prev_winner["fixed_code"], prev_winner["run"], base_feedback,
        )
        kw = dict(mode=f"{mode_name}", model_name=model_name, k=1, task_type="optimize") \
             if backend == "local" else dict(mode=f"{mode_name}", k=1, task_type="optimize")
        new_out = _repair_call(
            buggy_code=sample["buggy_code"],
            feedback=repair_fb,
            **kw,
        )
        new_runs = _eval_candidates(mode_name, new_out,
                                    label_offset=k + round_idx)
        return new_runs[0]    # k=1 by design

    def _iterate_speedup_round(mode_name, base_feedback, prev_winner,
                                round_idx, label_offset):
        """Single iterate-on-speedup round. Asks for a strictly faster version."""
        speedup_fb = format_iterate_speedup_feedback(
            prev_winner["fixed_code"], prev_winner["run"],
            baseline_ms=baseline_ms,
            current_speedup=(baseline_ms / prev_winner["run"]["mean_ms"]
                             if prev_winner["run"].get("mean_ms") else 1.0),
            base_feedback=base_feedback,
        )
        kw = dict(mode=f"{mode_name}", model_name=model_name, k=1, task_type="optimize") \
             if backend == "local" else dict(mode=f"{mode_name}", k=1, task_type="optimize")
        new_out = _repair_call(
            buggy_code=sample["buggy_code"],
            feedback=speedup_fb,
            **kw,
        )
        new_runs = _eval_candidates(mode_name, new_out, label_offset=label_offset)
        return new_runs[0]

    def _run_mode(mode_name: str, fn, *args, base_feedback=None):
        if verbose:
            tag = backend if backend != "local" else model_name
            print(f"\n[{mode_name.capitalize()} mode] Calling LLM ({backend}: {tag}, k={k})...")
        t0 = time.time()
        repair_out = fn(*args)
        elapsed = time.time() - t0

        candidate_runs = _eval_candidates(mode_name, repair_out)
        win_idx, winner, any_correct = _select_winner(candidate_runs, baseline_ms)

        # ── Self-repair retry loop ────────────────────────────────────────────
        repair_history = []
        if not any_correct and repair_rounds > 0:
            prev_winner = winner   # least-bad failed candidate
            for round_idx in range(repair_rounds):
                if verbose:
                    fm = prev_winner["run"].get("failure_mode") or "?"
                    print(f"  [Self-repair round {round_idx+1}] prev_failure={fm}")
                tr = time.time()
                new_cand = _self_repair_round(mode_name, base_feedback,
                                              prev_winner, round_idx)
                round_elapsed = time.time() - tr
                candidate_runs.append(new_cand)
                new_run = new_cand["run"]
                round_passed = new_run["passed"]
                round_speedup = (baseline_ms / new_run["mean_ms"]) if (
                    round_passed and baseline_ms and new_run.get("mean_ms")) else None
                repair_history.append({
                    "round": round_idx + 1,
                    "prev_failure_mode": prev_winner["run"].get("failure_mode"),
                    "new_passed": round_passed,
                    "new_failure_mode": new_run.get("failure_mode"),
                    "new_speedup": round(round_speedup, 3) if round_speedup else None,
                    "elapsed_s": round(round_elapsed, 2),
                })
                if verbose:
                    sp_str = f"{round_speedup:.2f}x" if round_speedup else "—"
                    fm = new_run.get("failure_mode") or "ok"
                    print(f"    -> passed={round_passed}  failure={fm}  speedup={sp_str}  "
                          f"({round_elapsed:.1f}s)")
                if round_passed:
                    win_idx = len(candidate_runs) - 1   # this new candidate
                    winner = new_cand
                    any_correct = True
                    break
                prev_winner = new_cand
                # Re-pick least-bad across all (in case the new attempt is
                # less bad than earlier ones)
                _, winner, _ = _select_winner(candidate_runs, baseline_ms)
                win_idx = candidate_runs.index(winner)

        # ── Iterate-on-speedup loop (only fires when winner is correct) ──────
        iterate_history = []
        if any_correct and iterate_speedup_rounds > 0 and baseline_ms:
            current_speedup = baseline_ms / winner["run"]["mean_ms"] \
                              if winner["run"].get("mean_ms") else 1.0
            for round_idx in range(iterate_speedup_rounds):
                if verbose:
                    print(f"  [Iterate-speedup round {round_idx+1}] "
                          f"current speedup={current_speedup:.2f}×")
                tr = time.time()
                new_cand = _iterate_speedup_round(
                    mode_name, base_feedback, winner, round_idx,
                    label_offset=len(candidate_runs),
                )
                round_elapsed = time.time() - tr
                candidate_runs.append(new_cand)
                new_run = new_cand["run"]
                new_speedup = (baseline_ms / new_run["mean_ms"]) if (
                    new_run.get("passed") and new_run.get("mean_ms")) else None
                accepted = (new_run.get("passed") and new_speedup is not None
                            and new_speedup > current_speedup)
                iterate_history.append({
                    "round": round_idx + 1,
                    "prev_speedup": round(current_speedup, 3),
                    "new_passed": new_run["passed"],
                    "new_failure_mode": new_run.get("failure_mode"),
                    "new_speedup": round(new_speedup, 3) if new_speedup else None,
                    "accepted": accepted,
                    "elapsed_s": round(round_elapsed, 2),
                })
                if verbose:
                    sp = f"{new_speedup:.2f}x" if new_speedup else "—"
                    fm = new_run.get("failure_mode") or "ok"
                    tag = "accepted" if accepted else "rejected"
                    print(f"    -> passed={new_run['passed']}  speedup={sp}  "
                          f"failure={fm}  ({tag}, {round_elapsed:.1f}s)")
                if accepted:
                    win_idx = len(candidate_runs) - 1
                    winner = new_cand
                    current_speedup = new_speedup
                # If the new candidate is wrong/worse, keep the previous winner
                # and try again from THAT one (not the rejected attempt)

        run = winner["run"]
        speedup = (baseline_ms / run["mean_ms"]) if (
            run.get("passed") and baseline_ms and run.get("mean_ms")) else None

        # Per-candidate compact summary for the JSONL
        cand_summary = [
            {
                "idx": i, "passed": c["run"]["passed"],
                "compiled": c["run"]["compiled"],
                "failure_mode": c["run"].get("failure_mode"),
                "mean_ms": c["run"].get("mean_ms"),
                "speedup": (round(baseline_ms / c["run"]["mean_ms"], 3)
                            if c["run"]["passed"] and baseline_ms
                            and c["run"].get("mean_ms") else None),
                "from_repair": i >= k,            # was this candidate produced by self-repair?
            }
            for i, c in enumerate(candidate_runs)
        ]
        n_correct = sum(1 for c in cand_summary if c["passed"])

        repair_out.update({
            "elapsed_s": round(elapsed, 2),
            "winner_idx": win_idx,
            "k_correct": n_correct,
            "passed_at_k": any_correct,
            "n_candidates_total": len(candidate_runs),
            "repair_rounds_used": len(repair_history),
            "repair_history": repair_history,
            "iterate_speedup_rounds_used": len(iterate_history),
            "iterate_speedup_history": iterate_history,
            # Winner-flattened fields (back-compat with single-candidate schema)
            "compiled": run["compiled"],
            "passed": run["passed"],
            "failure_mode": run.get("failure_mode"),
            "mean_ms": run.get("mean_ms"),
            "median_ms": run.get("median_ms"),
            "speedup": round(speedup, 3) if speedup else None,
            "compile_error": run.get("compile_error", "")[:500],
            "per_test": [
                {kk: t[kk] for kk in ("idx", "passed", "mean_ms", "timed_out", "failure_mode")}
                for t in run.get("per_test", [])
            ],
            "candidates_summary": cand_summary,
            "raw_response": repair_out.get("raw_response", "")[:2000],
            "fixed_code": winner["fixed_code"],
        })
        repair_out.pop("candidates", None)

        if verbose:
            sp = f"{repair_out['speedup']}x" if repair_out['speedup'] else "—"
            fm = run.get("failure_mode") or "ok"
            extra = f"  (incl. {len(repair_history)} repair rounds)" if repair_history else ""
            print(f"  k={k} correct={n_correct}/{len(candidate_runs)}  pass@k={any_correct}  "
                  f"winner_idx={win_idx}  failure={fm}  "
                  f"mean={run.get('mean_ms')} ms  speedup={sp}  ({elapsed:.1f}s){extra}")
        # Expose for the artifact writer
        _run_mode._last_candidate_runs = candidate_runs
        return repair_out

    if "static" in modes:
        result["static"] = _run_mode("static", _static_fn,
                                     sample["buggy_code"],
                                     base_feedback=None)
        if sample_dir and result["static"] is not None:
            _write_mode_candidates(sample_dir, "static",
                                   _run_mode._last_candidate_runs,
                                   result["static"],
                                   original_code=sample["buggy_code"],
                                   original_name="v0_slow.cpp")
    if "dynamic" in modes and runtime_feedback:
        result["dynamic"] = _run_mode("dynamic", _dynamic_fn,
                                      sample["buggy_code"], runtime_feedback,
                                      base_feedback=runtime_feedback)
        if sample_dir and result["dynamic"] is not None:
            _write_mode_candidates(sample_dir, "dynamic",
                                   _run_mode._last_candidate_runs,
                                   result["dynamic"],
                                   original_code=sample["buggy_code"],
                                   original_name="v0_slow.cpp")
    if "profiling" in modes and profile_summary:
        result["profiling"] = _run_mode("profiling", _profiling_fn,
                                        profile_buggy_code, profile_summary,
                                        base_feedback=profile_summary)
        if sample_dir and result["profiling"] is not None:
            # For profiling mode the LLM saw the annotated source — but the diff
            # is more readable when compared against the original (unannotated)
            # v0_slow.cpp.
            _write_mode_candidates(sample_dir, "profiling",
                                   _run_mode._last_candidate_runs,
                                   result["profiling"],
                                   original_code=sample["buggy_code"],
                                   original_name="v0_slow.cpp")

    # Per-sample summary (mirror of the JSONL row)
    if sample_dir:
        _write_json(os.path.join(sample_dir, "summary.json"), result)

    return result


def _resolve_modes(mode_arg: str):
    if mode_arg == "all":
        return ALL_MODES
    return (mode_arg,)


def main():
    parser = argparse.ArgumentParser(description="Profile-Guided Code Correction & Optimisation")
    parser.add_argument("--dataset", choices=["synthetic", "pie"], default="synthetic",
                        help="synthetic = data/bugs.py (correctness); pie = PIE CodeNet (speedup)")
    parser.add_argument("--samples", type=int, default=None,
                        help="Number of samples to run (default: all for synthetic, 5 for pie)")
    parser.add_argument("--id", type=str, default=None,
                        help="Run only the sample with this id")
    parser.add_argument("--mode", choices=["static", "dynamic", "profiling", "all"],
                        default="all",
                        help="Which repair/optimisation mode(s) to run.")
    parser.add_argument("--backend", choices=["anthropic", "local"], default="local",
                        help="LLM backend: 'local' (HuggingFace) or 'anthropic'")
    parser.add_argument("--model", type=str, default=LOCAL_DEFAULT_MODEL,
                        help=f"Model name (local backend). Default: {LOCAL_DEFAULT_MODEL}")
    parser.add_argument("--pie-min-improvement", type=float, default=30.0,
                        help="PIE filter: minimum oracle improvement_frac to consider (default 30%)")
    parser.add_argument("--pie-max-lines", type=int, default=80,
                        help="PIE filter: max LOC of slow code to keep (default 80)")
    parser.add_argument("--pie-min-baseline-cputime", type=float, default=0.0,
                        help="PIE filter: minimum cpu_time_v0 (ms) to keep. "
                             "Use >=100 for meaningful gprof attribution.")
    parser.add_argument("--k", type=int, default=1,
                        help="Number of candidates per (sample, mode). k=1 = greedy. "
                             "k>1 enables sampling and pass@k.")
    parser.add_argument("--temperature", type=float, default=0.6,
                        help="Sampling temperature when k>1 (ignored at k=1).")
    parser.add_argument("--repair-rounds", type=int, default=0,
                        help="Self-repair retry rounds when all initial k "
                             "candidates fail. Each round = 1 greedy LLM call "
                             "with augmented failure feedback.")
    parser.add_argument("--iterate-speedup-rounds", type=int, default=0,
                        help="When the winning candidate is correct, run extra "
                             "rounds asking the LLM for a strictly faster "
                             "version. Only applies to PIE.")
    parser.add_argument("--seed", type=int, default=0,
                        help="Sampling seed (used when k>1). Vary across runs "
                             "to estimate sampling variance.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    modes = _resolve_modes(args.mode)

    # ── Load samples ──────────────────────────────────────────────────────────
    if args.dataset == "pie":
        from data.pie_loader import load_pie_samples
        n = args.samples if args.samples else 5
        samples = load_pie_samples(
            n=n,
            min_improvement=args.pie_min_improvement,
            max_lines=args.pie_max_lines,
            min_cpu_time_v0=args.pie_min_baseline_cputime,
        )
        runner = run_pie_sample
    else:
        samples = SYNTHETIC_SAMPLES
        if args.samples:
            samples = samples[:args.samples]
        runner = run_sample

    if args.id:
        samples = [s for s in samples if s["id"] == args.id]
        if not samples:
            print(f"No sample with id={args.id}")
            sys.exit(1)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    run_tag = args.model.split("/")[-1] if args.backend == "local" else "anthropic"
    results_path = os.path.join(
        RESULTS_DIR, f"results_{args.dataset}_{run_tag}.jsonl",
    )

    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_meta = {
        "run_id": run_id,
        "dataset": args.dataset,
        "model": args.model,
        "backend": args.backend,
        "modes": list(modes),
        "k": args.k,
        "temperature": args.temperature if args.k > 1 else 0.0,
        "repair_rounds": args.repair_rounds,
        "iterate_speedup_rounds": args.iterate_speedup_rounds,
        "seed": args.seed,
        "pie_min_improvement": args.pie_min_improvement,
        "pie_max_lines": args.pie_max_lines,
        "pie_min_baseline_cputime": args.pie_min_baseline_cputime,
    }

    # Per-run artifact directory: results/run_<timestamp>/
    run_dir = os.path.join(RESULTS_DIR, f"run_{run_id}")
    os.makedirs(run_dir, exist_ok=True)
    _write_json(os.path.join(run_dir, "meta.json"), run_meta)
    run_results_jsonl = os.path.join(run_dir, "results.jsonl")
    print(f"[Run dir] {run_dir}")

    all_results = []
    runner_kw = dict(modes=modes, verbose=not args.quiet,
                     backend=args.backend, model_name=args.model,
                     k=args.k, temperature=args.temperature,
                     repair_rounds=args.repair_rounds, seed=args.seed,
                     run_dir=run_dir)
    if runner is run_pie_sample:
        runner_kw["iterate_speedup_rounds"] = args.iterate_speedup_rounds
    for sample in samples:
        r = runner(sample, **runner_kw)
        r["run_id"] = run_id
        r["run_meta"] = run_meta
        all_results.append(r)
        # Append to both the global ledger and the per-run results.jsonl
        with open(results_path, "a") as f:
            f.write(json.dumps(r) + "\n")
        with open(run_results_jsonl, "a") as f:
            f.write(json.dumps(r) + "\n")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    metric_label = f"pass@{args.k}" if args.k > 1 else "pass@1"
    print(f"SUMMARY  ({args.dataset}, {len(all_results)} samples, "
          f"modes={','.join(modes)}, {metric_label})")
    print(f"{'='*70}")

    def _status(entry):
        if not entry:
            return "  -"
        if entry["passed"]:
            return "PASS"
        return "FAIL" if entry["compiled"] else "ERR"

    if args.dataset == "pie":
        # Per-row: PASS shows speedup; FAIL/ERR shows the failure mode
        mode_col_w = 22
        header = f"{'ID':<32}" + "".join(f"{m:>{mode_col_w}}" for m in modes)
        print(header)
        print("-" * len(header))
        for r in all_results:
            cells = []
            for m in modes:
                e = r.get(m)
                if e is None:
                    cells.append("—")
                elif e["passed"]:
                    sp = f"{e['speedup']:.2f}x" if e.get("speedup") is not None else "?"
                    cells.append(f"PASS {sp}")
                else:
                    fm = e.get("failure_mode") or ("compile" if not e["compiled"] else "?")
                    tag = "ERR" if fm == "compile" else "FAIL"
                    cells.append(f"{tag} ({fm})")
            row = f"{r['id']:<32}" + "".join(f"{c:>{mode_col_w}}" for c in cells)
            print(row)

        n = len(all_results)
        print()
        def _quantile(xs, q):
            if not xs:
                return None
            xs_sorted = sorted(xs)
            k = (len(xs_sorted) - 1) * q
            lo, hi = int(k), min(int(k) + 1, len(xs_sorted) - 1)
            return xs_sorted[lo] + (xs_sorted[hi] - xs_sorted[lo]) * (k - int(k))

        for m in modes:
            entries = [r.get(m) for r in all_results if r.get(m)]
            passed = sum(1 for e in entries if e["passed"])
            speedups = [e["speedup"] for e in entries
                        if e["passed"] and e.get("speedup") is not None]
            faster = sum(1 for s in speedups if s > 1.0)
            med_sp  = statistics.median(speedups) if speedups else None
            mean_sp = statistics.mean(speedups)   if speedups else None
            max_sp  = max(speedups) if speedups else None
            p25     = _quantile(speedups, 0.25)
            p75     = _quantile(speedups, 0.75)
            # Failure-mode breakdown across the failures
            fail_counts = {}
            for e in entries:
                if not e["passed"]:
                    fm = e.get("failure_mode") or ("compile" if not e["compiled"] else "unknown")
                    fail_counts[fm] = fail_counts.get(fm, 0) + 1
            fail_str = ", ".join(f"{k}={v}" for k, v in sorted(fail_counts.items())) or "—"

            def _fmt(x): return f"{x:.2f}x" if x is not None else "—"
            print(f"{m.capitalize():<10} {metric_label}: {passed}/{n} = {passed/n*100:.0f}%   "
                  f"faster: {faster}/{n}   "
                  f"speedup mean={_fmt(mean_sp)} median={_fmt(med_sp)} "
                  f"p25={_fmt(p25)} p75={_fmt(p75)} max={_fmt(max_sp)}   "
                  f"failures: [{fail_str}]")
    else:
        mode_col_w = 10
        header = f"{'ID':<30}" + "".join(f"{m:>{mode_col_w}}" for m in modes)
        print(header)
        print("-" * len(header))
        for r in all_results:
            row = f"{r['id']:<30}" + "".join(f"{_status(r.get(m)):>{mode_col_w}}" for m in modes)
            print(row)
        n = len(all_results)
        print()
        for m in modes:
            passed = sum(1 for r in all_results if r.get(m) and r[m]["passed"])
            print(f"{m.capitalize():<10} {metric_label}: {passed}/{n} = {passed/n*100:.0f}%")

    # ── Build a structured summary that mirrors the printed table ────────────
    def _quantile_safe(xs, q):
        if not xs: return None
        xs_sorted = sorted(xs); kk = (len(xs_sorted) - 1) * q
        lo, hi = int(kk), min(int(kk) + 1, len(xs_sorted) - 1)
        return xs_sorted[lo] + (xs_sorted[hi] - xs_sorted[lo]) * (kk - int(kk))

    summary = {"run_id": run_id, "meta": run_meta, "n_samples": len(all_results),
               "per_mode": {}}
    for m in modes:
        entries = [r.get(m) for r in all_results if r.get(m)]
        passed = sum(1 for e in entries if e["passed"])
        speedups = [e["speedup"] for e in entries
                    if e["passed"] and e.get("speedup") is not None]
        fail_counts = {}
        for e in entries:
            if not e["passed"]:
                fm = e.get("failure_mode") or ("compile" if not e["compiled"] else "unknown")
                fail_counts[fm] = fail_counts.get(fm, 0) + 1
        summary["per_mode"][m] = {
            "correct": passed,
            "total": len(all_results),
            "correct_pct": round(passed / max(1, len(all_results)) * 100, 1),
            "faster_count": sum(1 for s in speedups if s > 1.0) if speedups else 0,
            "speedup_mean":   round(statistics.mean(speedups), 3) if speedups else None,
            "speedup_median": round(statistics.median(speedups), 3) if speedups else None,
            "speedup_p25":    round(_quantile_safe(speedups, 0.25), 3) if speedups else None,
            "speedup_p75":    round(_quantile_safe(speedups, 0.75), 3) if speedups else None,
            "speedup_max":    round(max(speedups), 3) if speedups else None,
            "failures":       fail_counts,
        }
    _write_json(os.path.join(run_dir, "summary.json"), summary)

    # Human-readable README in the run dir
    readme_lines = [
        f"# Run {run_id}",
        f"",
        f"- Dataset: `{run_meta['dataset']}`",
        f"- Model: `{run_meta['model']}` ({run_meta['backend']})",
        f"- Modes: {', '.join(run_meta['modes'])}",
        f"- k={run_meta['k']}, temperature={run_meta['temperature']}, "
        f"seed={run_meta['seed']}, repair_rounds={run_meta['repair_rounds']}, "
        f"iterate_speedup_rounds={run_meta['iterate_speedup_rounds']}",
        f"- Samples: {len(all_results)}",
        f"",
        f"## Per-mode summary",
        f"",
        f"| Mode | Correct | Faster | Mean spd | Median spd | Max spd | Failures |",
        f"|---|---|---|---|---|---|---|",
    ]
    for m in modes:
        s = summary["per_mode"][m]
        def fx(x): return f"{x:.2f}x" if x is not None else "—"
        readme_lines.append(
            f"| {m} | {s['correct']}/{s['total']} ({s['correct_pct']:.0f}%) | "
            f"{s['faster_count']}/{s['total']} | "
            f"{fx(s['speedup_mean'])} | {fx(s['speedup_median'])} | "
            f"{fx(s['speedup_max'])} | "
            f"{', '.join(f'{k}={v}' for k,v in sorted(s['failures'].items())) or '—'} |"
        )
    readme_lines += [
        f"",
        f"## Layout",
        f"",
        f"```",
        f"run_{run_id}/",
        f"├── meta.json          # full run configuration",
        f"├── summary.json       # aggregate per-mode stats (mirrors the table above)",
        f"├── results.jsonl      # one row per sample (also appended to the global ledger)",
        f"└── samples/",
        f"    └── <sample_id>/",
        f"        ├── v0_*.cpp                  # input (slow / buggy) code",
        f"        ├── v1_*.cpp                  # gold reference (fast / fixed)",
        f"        ├── oracle_v0_to_v1.diff      # gold reference diff (slow -> fast)",
        f"        ├── sample_meta.json          # sample metadata",
        f"        ├── baseline_timing.json      # slow code timing (PIE only)",
        f"        ├── baseline_run.json         # buggy run result (synthetic only)",
        f"        ├── gprof_flat.txt            # profile artifacts (if profiling mode)",
        f"        ├── perf_stat.txt",
        f"        ├── hotspots.json",
        f"        ├── annotated_source.cpp",
        f"        ├── prompt_runtime_feedback.txt",
        f"        ├── prompt_profile_summary.txt",
        f"        ├── summary.json              # per-sample summary (row from results.jsonl)",
        f"        └── <mode>/                   # one folder per mode that ran",
        f"            ├── candidate_<i>.cpp           # each generated candidate",
        f"            ├── candidate_<i>_vs_v0.diff    # candidate-vs-original diff",
        f"            ├── candidate_<i>_run.json",
        f"            ├── winner.cpp                  # the chosen winning candidate",
        f"            ├── winner_vs_v0.diff           # winner-vs-original diff",
        f"            └── summary.json                # this mode's row from the JSONL",
        f"```",
    ]
    _write_text(os.path.join(run_dir, "README.md"), "\n".join(readme_lines))

    print(f"\nResults saved to: {results_path}")
    print(f"Per-run artifacts in: {run_dir}")


if __name__ == "__main__":
    main()
