"""
Run gprof and/or perf stat on a compiled binary, then format the output
into a concise natural-language summary suitable for an LLM prompt.
"""
import os
import subprocess
import re
from config import RUN_TIMEOUT, PERF_EVENTS, USE_PERF, WORKSPACE_DIR


def run_gprof(binary_path: str, stdin_data: str = "") -> str:
    """
    Execute the binary (generating gmon.out) then run gprof on it.
    Returns the flat profile section as a string, or an error message.
    """
    work_dir = os.path.dirname(binary_path)
    env = os.environ.copy()
    env["GMON_OUT_PREFIX"] = os.path.join(work_dir, "gmon")

    # Run binary to generate gmon.out
    stdin_bytes = (stdin_data.encode("utf-8", errors="replace")
                   if isinstance(stdin_data, str) else (stdin_data or b""))
    try:
        subprocess.run(
            [binary_path], input=stdin_bytes, capture_output=True, text=False,
            timeout=RUN_TIMEOUT, env=env, cwd=work_dir
        )
    except subprocess.TimeoutExpired:
        return "gprof: binary timed out during profiling run"

    # Find generated gmon file
    gmon_files = [f for f in os.listdir(work_dir) if f.startswith("gmon")]
    if not gmon_files:
        return "gprof: no gmon.out generated (binary may not have been compiled with -pg)"

    gmon_path = os.path.join(work_dir, gmon_files[0])
    try:
        proc = subprocess.run(
            ["gprof", "-b", binary_path, gmon_path],
            capture_output=True, text=True, timeout=15
        )
        if proc.returncode != 0:
            return f"gprof error: {proc.stderr[:300]}"
        # Return only the flat profile (first section)
        output = proc.stdout
        # Extract up to the first blank-line-separated block
        lines = output.split("\n")
        section = []
        in_flat = False
        for line in lines:
            if "Flat profile" in line or "% cumulative" in line:
                in_flat = True
            if in_flat:
                section.append(line)
            if in_flat and line.strip() == "" and len(section) > 5:
                break
        return "\n".join(section[:40]) if section else output[:800]
    except subprocess.TimeoutExpired:
        return "gprof: timed out"
    except Exception as e:
        return f"gprof: exception: {e}"


def run_perf_stat(binary_path: str, stdin_data: str = "") -> str:
    """
    Run `perf stat` on the binary and return the summary.
    Falls back gracefully if perf is unavailable or lacks privileges.
    """
    if not USE_PERF:
        return "perf: disabled in config"
    stdin_bytes = (stdin_data.encode("utf-8", errors="replace")
                   if isinstance(stdin_data, str) else (stdin_data or b""))
    try:
        proc = subprocess.run(
            ["perf", "stat", "-e", PERF_EVENTS, binary_path],
            input=stdin_bytes,
            capture_output=True, text=False, timeout=RUN_TIMEOUT + 5
        )
        # perf stat writes to stderr
        out_b = proc.stderr or proc.stdout or b""
        output = out_b.decode("utf-8", errors="replace")
        if "Permission denied" in output or "paranoid" in output:
            return "perf: insufficient privileges (run as root or lower /proc/sys/kernel/perf_event_paranoid)"
        # Keep only the stat lines
        lines = [l for l in output.split("\n") if l.strip()]
        return "\n".join(lines[:30])
    except FileNotFoundError:
        return "perf: not found on PATH"
    except subprocess.TimeoutExpired:
        return "perf: timed out"
    except Exception as e:
        return f"perf: exception: {e}"


def profile(binary_path: str, stdin_data: str = "") -> dict:
    """
    Run all profiling tools and return a dict with raw outputs.
    """
    return {
        "gprof": run_gprof(binary_path, stdin_data=stdin_data),
        "perf_stat": run_perf_stat(binary_path, stdin_data=stdin_data),
    }


def format_runtime_feedback(compile_warnings: str = "",
                            actual_output: str = "", expected_output: str = "") -> str:
    """
    Build the prompt block for the 'dynamic' mode: runtime output diff
    and compiler warnings only — NO gprof / perf data.
    """
    lines = ["=== Dynamic Execution Feedback ==="]

    if actual_output or expected_output:
        lines.append(f"\n[Runtime Output]")
        if actual_output is not None:
            lines.append(f"  Actual:   {repr(actual_output.strip())}")
        if expected_output:
            lines.append(f"  Expected: {repr(expected_output.strip())}")

    if compile_warnings.strip():
        lines.append(f"\n[Compiler Warnings]\n{compile_warnings.strip()[:400]}")

    lines.append(
        "\nUse the above runtime output diff to identify how the program's "
        "observed behaviour deviates from expectation."
    )
    return "\n".join(lines)


def format_pie_runtime_feedback(per_test: list, mean_ms: float) -> str:
    """
    Dynamic-mode prompt block for PIE samples: timing info + correctness summary
    across all test cases. NO gprof / perf data.
    """
    lines = ["=== Dynamic Execution Feedback ==="]
    lines.append(f"\nThe current program is correct on all test cases but slow.")
    lines.append(f"Average runtime: {mean_ms:.2f} ms across {len(per_test)} test cases.\n")
    lines.append("[Per-test-case timings]")
    for t in per_test:
        m = t.get("mean_ms")
        m_str = f"{m:.2f} ms" if m is not None else "n/a"
        lines.append(f"  test #{t['idx']}: {m_str}  (passed={t['passed']})")
    lines.append(
        "\nProduce a faster version that preserves identical output for every "
        "test case. Focus on algorithmic complexity and I/O efficiency."
    )
    return "\n".join(lines)


def parse_gprof_hotspots(gprof_output: str, min_pct: float = 1.0) -> list:
    """
    Extract (function_name, pct_time, calls) from a gprof flat-profile string.
    Skips entries with no time and STL/internal noise (anything starting with `std::`
    or `__`). Returns a list of dicts sorted by pct_time desc.
    """
    if not gprof_output or gprof_output.startswith("gprof:"):
        return []
    hotspots = []
    in_flat = False
    for line in gprof_output.split("\n"):
        s = line.strip()
        if "% cumulative" in line or "Flat profile" in line or s.startswith("time"):
            in_flat = True
            continue
        if not in_flat or not s:
            continue
        cols = s.split(None, 6)
        if len(cols) < 7:
            continue
        try:
            pct = float(cols[0])
        except ValueError:
            continue
        if pct < min_pct:
            continue
        try:
            calls = int(cols[3])
        except ValueError:
            calls = None
        name = cols[6].strip()
        if name.startswith(("std::", "__", "operator")) or "::" in name:
            continue
        # Strip parameter list to get the bare identifier
        bare = name.split("(", 1)[0].strip()
        if not bare or not bare.replace("_", "").isalnum():
            continue
        hotspots.append({"name": bare, "full_name": name, "pct": pct, "calls": calls})
    return sorted(hotspots, key=lambda h: -h["pct"])


def parse_gprof_top_entries(gprof_output: str, n: int = 4,
                             min_pct: float = 1.0) -> list:
    """
    Like parse_gprof_hotspots but does NOT filter STL / internal entries —
    used for file-level fallback summary when no user-function hotspots match.
    Returns up to n entries with cleaned-up display names.
    """
    if not gprof_output or gprof_output.startswith("gprof:"):
        return []
    out = []
    in_flat = False
    for line in gprof_output.split("\n"):
        s = line.strip()
        if "% cumulative" in line or "Flat profile" in line or s.startswith("time"):
            in_flat = True
            continue
        if not in_flat or not s:
            continue
        cols = s.split(None, 6)
        if len(cols) < 7:
            continue
        try:
            pct = float(cols[0])
        except ValueError:
            continue
        if pct < min_pct:
            continue
        try:
            calls = int(cols[3])
        except ValueError:
            calls = None
        full_name = cols[6].strip()
        # Trim parameter list and template noise to keep things readable.
        # Examples:
        #   std::__cxx11::_List_base<std::pair<int, int>>::_M_clear()
        #     -> std::list::_M_clear
        #   __gnu_cxx::new_allocator<...>::~new_allocator()
        #     -> __gnu_cxx::new_allocator::~new_allocator
        display = full_name.split("(", 1)[0]
        # collapse template params <...> recursively
        depth = 0
        cleaned_chars = []
        for ch in display:
            if ch == "<":
                depth += 1
                continue
            if ch == ">":
                depth = max(0, depth - 1)
                continue
            if depth == 0:
                cleaned_chars.append(ch)
        display = "".join(cleaned_chars).strip()
        # Friendly aliases for common STL bases
        display = (display
                   .replace("std::__cxx11::_List_base", "std::list")
                   .replace("std::__cxx11::list", "std::list")
                   .replace("std::__cxx11::basic_string", "std::string"))
        out.append({"display": display, "pct": pct, "calls": calls})
        if len(out) >= n:
            break
    return out


def annotate_source_with_hotspots(source: str, hotspots: list,
                                   gprof_output: str = "",
                                   max_annotations: int = 4) -> str:
    """
    Insert `// HOTSPOT: X% time, N calls (gprof)` comments above function
    definitions whose name appears in `hotspots`. If no per-function annotation
    can be inserted (e.g. all hotspots are STL internals), fall back to a
    file-level header comment summarising the top gprof entries from
    `gprof_output`.
    """
    annotated_names = set()
    lines = source.split("\n")
    out = []
    name_to_info = {h["name"]: h for h in hotspots[:max_annotations]}
    import re as _re
    for i, line in enumerate(lines):
        for name, info in list(name_to_info.items()):
            if name in annotated_names:
                continue
            pat = _re.compile(rf"\b{_re.escape(name)}\s*\(")
            if not pat.search(line):
                continue
            before = line[:line.find(name)]
            if not before.strip():
                continue
            joined = line
            for j in range(i + 1, min(i + 3, len(lines))):
                joined += " " + lines[j]
                if "{" in joined:
                    break
            if "{" not in joined:
                continue
            calls_str = f", {info['calls']} calls" if info["calls"] else ""
            comment = (f"// HOTSPOT: {info['pct']:.1f}% of runtime"
                       f"{calls_str} (per gprof — focus optimisation here)")
            out.append(comment)
            annotated_names.add(name)
            break
        out.append(line)

    if annotated_names:
        return "\n".join(out)

    # Fallback: no user-source line was annotated. Prepend a file-level
    # comment summarising the top gprof entries — usually STL hotspots that
    # the model can address by switching data structures or I/O routines.
    top = parse_gprof_top_entries(gprof_output)
    if not top:
        return source
    header = ["// === HOTSPOT FILE-LEVEL SUMMARY (per gprof) ==="]
    header.append("// No user-defined function appears in the flat profile, but most "
                  "runtime is spent in:")
    for h in top:
        calls_str = f", {h['calls']} calls" if h['calls'] else ""
        header.append(f"//   - {h['pct']:.1f}% in {h['display']}{calls_str}")
    header.append("// Consider whether the data structures or I/O routines you "
                  "use here are the right ones.")
    header.append("")
    return "\n".join(header) + "\n" + source


def format_iterate_speedup_feedback(prev_code: str, prev_run: dict,
                                     baseline_ms: float, current_speedup: float,
                                     base_feedback: str = None) -> str:
    """
    Build augmented feedback for an iterate-on-speedup retry. The candidate is
    correct; the LLM is asked to push it strictly faster while preserving
    correctness on every test case.
    """
    lines = []
    if base_feedback:
        lines.append(base_feedback.strip())
        lines.append("")
    lines.append("=== Iterate-on-Speedup Context ===")
    lines.append(f"Your previous attempt is correct on all test cases and ran "
                 f"{prev_run.get('mean_ms', '?')} ms on average "
                 f"(baseline {baseline_ms:.2f} ms, speedup {current_speedup:.2f}×). "
                 f"It is the current candidate:")
    lines.append("")
    lines.append("```cpp")
    lines.append(prev_code.strip())
    lines.append("```")
    lines.append("")
    lines.append("Produce a strictly FASTER version that still passes every "
                 "test case. Focus on the slowest code paths from the profile "
                 "(if available above). If you cannot make it any faster, "
                 "return this same code unchanged.")
    lines.append("")
    lines.append("Return ONLY the complete C++ source inside a single ```cpp ... ``` "
                 "fenced block. Do not include explanation.")
    return "\n".join(lines)


def format_self_repair_feedback(prev_code: str, prev_run: dict,
                                 base_feedback: str = None) -> str:
    """
    Build the augmented feedback for a self-repair retry. Combines the original
    mode-specific feedback (timing, profile, or none for static) with a
    description of the previous attempt's failure.
    """
    fm = prev_run.get("failure_mode")
    lines = []
    if base_feedback:
        lines.append(base_feedback.strip())
        lines.append("")
    lines.append("=== Self-Repair Context ===")
    lines.append("Your previous attempt at this task FAILED. The failed code was:")
    lines.append("")
    lines.append("```cpp")
    lines.append(prev_code.strip())
    lines.append("```")
    lines.append("")
    if fm == "compile":
        err = (prev_run.get("compile_error") or "").strip()[:1000]
        lines.append(f"[Failure: compile error]")
        lines.append(err if err else "(no compiler output captured)")
        lines.append("")
        lines.append("Fix the compilation error while preserving the optimisation intent.")
    elif fm == "wrong_output":
        fails = [t for t in (prev_run.get("per_test", []) or [])
                 if not t.get("passed")]
        lines.append(f"[Failure: wrong output on {len(fails)} test case(s)]")
        # Show up to 4 concrete examples; cap each output to keep the prompt small
        max_show = min(4, len(fails))
        per_case_cap = 250 if len(fails) > 1 else 500
        for t in fails[:max_show]:
            stdout = (t.get("stdout") or "").strip()[:per_case_cap]
            expected = (t.get("expected") or "").strip()[:per_case_cap]
            lines.append(f"  Test #{t.get('idx')}:")
            lines.append(f"    Expected: {expected!r}")
            lines.append(f"    Actual:   {stdout!r}")
        if len(fails) > max_show:
            lines.append(f"  ... and {len(fails) - max_show} more failing test case(s)")
        lines.append("")
        lines.append("Fix the logic so the output matches expected on EVERY test "
                     "case, while still being faster than the original.")
    elif fm == "timeout":
        lines.append("[Failure: timeout]")
        lines.append("The program did not finish within the time limit on at least one test case.")
        lines.append("This usually means an infinite loop, infinite recursion, or insufficient algorithmic speedup.")
        lines.append("")
        lines.append("Produce a correct version with better complexity.")
    elif fm == "runtime_error":
        lines.append("[Failure: runtime error]")
        rc = prev_run.get("returncode")
        lines.append(f"Process exited with returncode={rc} (likely a crash, segfault, or assertion).")
        lines.append("")
        lines.append("Fix the runtime error while preserving the optimisation intent.")
    else:
        lines.append("[Failure: unknown]")
        lines.append("The previous attempt did not pass. Produce a corrected version.")

    lines.append("")
    lines.append("Return ONLY the complete corrected C++ source inside a single ```cpp ... ``` "
                 "fenced block. Do not include explanation.")
    return "\n".join(lines)


def format_pie_profile_for_llm(profile_data: dict, per_test: list,
                                mean_ms: float) -> str:
    """
    Profiling-mode prompt block for PIE: timing + gprof + perf counters.
    """
    lines = ["=== Dynamic Execution Profile ==="]
    lines.append(f"\nThe current program is correct but slow.")
    lines.append(f"Average runtime: {mean_ms:.2f} ms across {len(per_test)} test cases.\n")
    lines.append("[Per-test-case timings]")
    for t in per_test:
        m = t.get("mean_ms")
        m_str = f"{m:.2f} ms" if m is not None else "n/a"
        lines.append(f"  test #{t['idx']}: {m_str}  (passed={t['passed']})")

    gprof = profile_data.get("gprof", "")
    if gprof and not gprof.startswith("gprof:"):
        lines.append(f"\n[gprof Flat Profile]\n{gprof[:1200]}")
    else:
        lines.append(f"\n[gprof] {gprof[:200]}")

    perf = profile_data.get("perf_stat", "")
    if perf and not perf.startswith("perf:"):
        lines.append(f"\n[perf stat]\n{perf[:600]}")
    else:
        lines.append(f"\n[perf] {perf[:200]}")

    lines.append(
        "\nUse the timing breakdown and the profile data above to identify the "
        "performance hotspots, and produce a faster version that preserves "
        "correctness on every test case."
    )
    return "\n".join(lines)


def format_profile_for_llm(profile_data: dict, compile_warnings: str = "",
                            actual_output: str = "", expected_output: str = "") -> str:
    """
    Build the prompt block for the 'profiling' mode: runtime output diff +
    gprof flat profile + perf stat counters.
    """
    lines = ["=== Dynamic Execution Profile ==="]

    if actual_output or expected_output:
        lines.append(f"\n[Runtime Output]")
        if actual_output is not None:
            lines.append(f"  Actual:   {repr(actual_output.strip())}")
        if expected_output:
            lines.append(f"  Expected: {repr(expected_output.strip())}")

    if compile_warnings.strip():
        lines.append(f"\n[Compiler Warnings]\n{compile_warnings.strip()[:400]}")

    gprof = profile_data.get("gprof", "")
    if gprof and not gprof.startswith("gprof:"):
        lines.append(f"\n[gprof Flat Profile]\n{gprof[:600]}")
    else:
        lines.append(f"\n[gprof] {gprof[:200]}")

    perf = profile_data.get("perf_stat", "")
    if perf and not perf.startswith("perf:"):
        lines.append(f"\n[perf stat]\n{perf[:400]}")
    else:
        lines.append(f"\n[perf] {perf[:200]}")

    lines.append(
        "\nUse the above runtime information to identify performance hotspots, "
        "abnormal instruction counts, or excessive branch mispredictions that may "
        "indicate correctness issues or inefficient code paths."
    )
    return "\n".join(lines)
