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


def run_gcov(binary_path: str, source_path: str,
             stdin_data: str = "") -> str:
    """
    Run a gcov-instrumented binary then `gcov` on its source. Returns the
    `.gcov` file content for the user's source as a string, or a `gcov: ...`
    error message.

    Implementation note: when compiled as `g++ src.cpp -o bin`, the runtime
    emits the .gcno/.gcda with names of the form `<bin_basename>-<src_stem>.gc{no,da}`
    (not `<src_stem>.gc*`). So `gcov src.cpp` fails to find them; we instead
    invoke `gcov <gcno_file>` directly. gcov then dumps one `.gcov` file per
    source/header touched (including all STL); we keep only the user-source one.
    """
    if not binary_path or not os.path.exists(binary_path):
        return "gcov: binary not available"
    work_dir = os.path.dirname(binary_path)
    stdin_bytes = (stdin_data.encode("utf-8", errors="replace")
                   if isinstance(stdin_data, str) else (stdin_data or b""))
    # 1. Run the binary so it emits a .gcda
    try:
        subprocess.run(
            [binary_path], input=stdin_bytes, capture_output=True,
            text=False, timeout=RUN_TIMEOUT, cwd=work_dir,
        )
    except subprocess.TimeoutExpired:
        return "gcov: binary timed out during instrumented run"
    # 2. Find the .gcno file (named "<binary_basename>-<src_stem>.gcno")
    gcno_files = [f for f in os.listdir(work_dir) if f.endswith(".gcno")]
    if not gcno_files:
        return "gcov: no .gcno file produced (compile flags wrong?)"
    gcno_path = gcno_files[0]
    # 3. Invoke gcov directly on the .gcno
    try:
        proc = subprocess.run(
            ["gcov", "-b", gcno_path],
            capture_output=True, text=True, timeout=15, cwd=work_dir,
        )
        if proc.returncode != 0:
            return f"gcov: gcov failed: {proc.stderr[:300]}"
    except subprocess.TimeoutExpired:
        return "gcov: gcov timed out"
    except FileNotFoundError:
        return "gcov: not found on PATH"
    # 4. Read the user's source-specific .gcov (ignore STL .gcov noise)
    src_basename = os.path.basename(source_path)
    user_gcov = os.path.join(work_dir, f"{src_basename}.gcov")
    if not os.path.exists(user_gcov):
        return f"gcov: no .gcov for user source (looked for {user_gcov})"
    try:
        text = open(user_gcov).read()
    except Exception as e:
        return f"gcov: read error: {e}"
    # 5. Clean up the STL .gcov files so they don't pile up across runs
    for f in os.listdir(work_dir):
        if f.endswith(".gcov") and f != f"{src_basename}.gcov":
            try: os.remove(os.path.join(work_dir, f))
            except OSError: pass
    return text


def parse_gcov_hot_lines(gcov_text: str, top_n: int = 10,
                         min_count: int = 100) -> list:
    """
    Parse a `.gcov` file's text and return the hottest lines.

    Returns a list of dicts: {line_no, count, source}. Excludes lines below
    min_count, non-executable lines (`-`), and never-executed lines (`#####`).
    Filters out trivial lines (braces, blank, single tokens) so the hot-list
    points at meaningful work.
    """
    if not gcov_text or gcov_text.startswith("gcov:"):
        return []
    hot = []
    for raw in gcov_text.splitlines():
        # Format: "       count: lineno: source code..."
        m = re.match(r"\s*([\d#-]+):\s*(\d+):\s?(.*)$", raw)
        if not m:
            continue
        count_str, lineno_str, src = m.group(1), m.group(2), m.group(3)
        # Skip non-executable, never-executed, and the gcov file header
        # ("- :   0:Source:..." etc.)
        if count_str in ("-", "#####") or lineno_str == "0":
            continue
        try:
            count = int(count_str)
        except ValueError:
            continue
        if count < min_count:
            continue
        # Skip trivial lines (just a brace, blank, single keyword)
        stripped = src.strip()
        if not stripped or stripped in {"{", "}", "};", "return;",
                                         "break;", "continue;"}:
            continue
        hot.append({"line_no": int(lineno_str), "count": count,
                    "source": stripped[:120]})
    # Highest count first
    return sorted(hot, key=lambda h: -h["count"])[:top_n]


def format_gcov_block(hot_lines: list, source_name: str = "v0_slow.cpp") -> str:
    """Format the gcov hot-lines list into a prompt-friendly block."""
    if not hot_lines:
        return ""
    lines = [f"[gcov line-level execution counts — top {len(hot_lines)} hot lines]"]
    for h in hot_lines:
        lines.append(
            f"  line {h['line_no']:>4}:  {h['count']:>12,} executions  | "
            f"{h['source']}"
        )
    lines.append("Lines executed many times are the hottest constant-factor "
                 "candidates. Consider whether the work on those lines can be "
                 "reduced, hoisted, or replaced with a cheaper operation.")
    return "\n".join(lines)


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


# Tag-conditional optimization checklists (option C from suggestion.md / §7.9).
# Designed to be CONSERVATIVE: each line is a safe, well-known transformation
# that a 7B model is known to be able to land. The goal is to constrain the
# model toward its existing optimisation vocabulary rather than tempt it into
# wholesale algorithmic rewrites.
TAG_OPTIMIZATION_CHECKLISTS = {
    "dp": [
        "Do NOT change the recurrence itself — the slow code's recurrence is the source of truth.",
        "Only tighten things that are clearly wasteful: oversized tables relative to the constraints, unused dimensions, unnecessary `long long` for small values.",
        "Add `ios_base::sync_with_stdio(false); cin.tie(nullptr);` if I/O is in a hot loop.",
    ],
    "graph": [
        "Do NOT change the traversal algorithm — preserve BFS as BFS, DFS as DFS, Dijkstra as Dijkstra.",
        "Only swap data structures when clearly wasteful (e.g. `std::map<int,...>` keyed on dense vertex IDs can be a `std::vector`).",
        "Add I/O sync if edges are read in a hot loop.",
    ],
    "tree": [
        "Do NOT change the tree-walk semantics — preserve the visit order.",
        "If the slow code allocates per-node containers inside the walk, hoist them out — but only if the per-node lifetime is purely local.",
    ],
    "string": [
        "Do NOT change string semantics — preserve comparison operators, substring boundaries, character ordering.",
        "If the slow code constructs new substrings in a loop, indexing into the original string is usually a safe drop-in.",
        "Add I/O sync if cin/cout is dominant.",
    ],
    "math": [
        "Do NOT change the mathematical formula — preserve the computation.",
        "If int overflow is plausible (products of values up to ~10^9), promote intermediates to `long long`.",
        "Do NOT introduce new tricks (sieves, modular inverse, FFT) unless the slow code already has one to refine.",
    ],
    "geometry": [
        "Do NOT change geometric predicates or precision assumptions.",
        "Replace `sqrt(d2)` with `d2` only when the comparison is `sqrt(d2) op c` with `c >= 0` — verify before doing.",
    ],
    "greedy": [
        "The slow code is usually already optimal up to constants — focus on I/O sync and container choice.",
        "Do NOT replace the greedy logic itself unless a clear bug is present.",
        "Add `ios_base::sync_with_stdio(false); cin.tie(nullptr);` if cin/cout is in a hot loop.",
    ],
    "simulation": [
        "Do NOT change the simulation semantics — preserve step order and state transitions.",
        "If the slow code stores a full history of states but only the latest is read, that's safe to drop.",
        "Add I/O sync if cin/cout is dominant in the simulation loop.",
    ],
    "data_structure": [
        "Do NOT change the data-structure semantics (e.g. don't swap ordered map for unordered map if iteration order is observed).",
        "Dense-int-keyed `std::map<int,...>` is a safe drop-in for `std::vector<...>` if you can prove keys stay in bounds.",
    ],
    "search": [
        "Do NOT change the search semantics — `lower_bound` vs `upper_bound` matter.",
        "Only replace hand-rolled binary search with `std::lower_bound` if the comparator and boundary handling are clearly equivalent.",
    ],
    "combinatorial": [
        "The slow code's enumeration is the source of truth — do NOT add bound-skipping tricks unless you can prove correctness.",
        "If the slow code materialises every combination in memory, scoring on the fly in the recursion is usually equivalent — but trace one example through to confirm.",
    ],
    "other": [
        "Apply I/O sync only — `ios_base::sync_with_stdio(false); cin.tie(nullptr);`.",
        "Do NOT change algorithmic shape; prefer constant-factor improvements (container choice, allocation patterns).",
    ],
    "unknown": [
        "Apply I/O sync only — `ios_base::sync_with_stdio(false); cin.tie(nullptr);`.",
        "Do NOT change algorithmic shape; the slow code is the source of truth for semantics.",
    ],
}


def format_tag_advice(tag: str) -> str:
    """
    Return a tag-conditional optimization checklist block for the prompt,
    or an empty string if the tag has no checklist registered.
    """
    if not tag:
        return ""
    items = TAG_OPTIMIZATION_CHECKLISTS.get(tag.lower())
    if not items:
        return ""
    lines = [f"Optimization Hints (this problem is classified as '{tag}'):"]
    for item in items:
        lines.append(f"  - {item}")
    lines.append(
        "These are cautionary suggestions, not a checklist to apply exhaustively. "
        "If a hint does not clearly fit the code in front of you, ignore it. "
        "Preserving the slow code's behaviour is more important than applying any hint."
    )
    return "\n".join(lines)


_COMPLEXITY_SUGGESTIONS = {
    "O(1)":          "Already constant-time. Focus on constant-factor only.",
    "O(log n)":      "Already near-optimal. Focus on constant-factor only.",
    "O(n)":          "Already linear. Constant-factor improvements only "
                     "(I/O sync, cache-friendly containers).",
    "O(n log n)":    "O(n log n) is usually near-optimal for sort/search "
                     "problems. Consider whether a true O(n) approach exists "
                     "(bucket sort, counting sort, hash table) — but only if "
                     "you can prove correctness.",
    "O(n^2)":        "Consider whether an O(n log n) or O(n) approach exists "
                     "(sort + sweep, two-pointer, hash table for lookups, "
                     "prefix sums, or replacing nested loop with a single "
                     "pass that maintains the needed state).",
    "O(n^2 log n)":  "Likely a nested loop with sort/search inside. Consider "
                     "moving the sort outside the loop, or replacing the inner "
                     "search with an O(1) hash lookup.",
    "O(n^3)":        "Consider whether an O(n^2) approach exists "
                     "(precomputed lookups, dropping a redundant loop). Then "
                     "consider whether O(n log n) is reachable.",
    "O(2^n)":        "Exponential — almost certainly a brute-force enumeration "
                     "or naive recursion. Memoise the recursion (top-down DP) "
                     "or rewrite as bottom-up DP; consider bitmask DP if the "
                     "state space is small. Plain recursion will not scale.",
}


def format_complexity_block(analysis: dict) -> str:
    """
    Build the Complexity Analysis prompt block.

    Expects an LLM-predictor dict: {"complexity": "O(n^2)",
                                     "predictor_id": "...", "raw": "..."}.
    Returns an empty string if `analysis` is falsy.
    """
    if not analysis:
        return ""
    complexity = analysis["complexity"]
    if complexity == "unknown":
        return ("Complexity Analysis (LLM-estimated from source):\n"
                "  Estimated complexity: unknown\n"
                "  The model could not classify the source into a standard "
                "Big-O class. Treat the source as the source of truth.")
    suggestion = _COMPLEXITY_SUGGESTIONS.get(
        complexity,
        "Slow code complexity is high. Consider whether a fundamentally "
        "faster algorithm exists (sorting, DP, hashing, divide-and-conquer)."
    )
    return ("Complexity Analysis (LLM-estimated from source):\n"
            f"  Estimated complexity: {complexity}\n"
            f"  Suggestion: {suggestion}\n"
            f"  (Static estimate by a code-LM. Use as a hint, not a guarantee.)")


def format_test_case_block(test_cases: list, max_chars: int = 600,
                           label: str = "Test Case") -> str:
    """
    Format the first test case as a concrete (Input, Expected Output) block.
    Mirrors EffiLearner's prompt structure: one anchoring example that grounds
    the rewrite without requiring the model to infer I/O contract from code.
    """
    if not test_cases:
        return ""
    tc = test_cases[0]
    stdin = (tc.get("input") or "").rstrip()
    expected = (tc.get("expected_output") or "").rstrip()
    if len(stdin) > max_chars:
        stdin = stdin[:max_chars].rstrip() + "\n[... truncated]"
    if len(expected) > max_chars:
        expected = expected[:max_chars].rstrip() + "\n[... truncated]"
    suffix = f" (one example of {len(test_cases)} total)" if len(test_cases) > 1 else ""
    return (f"{label}{suffix}:\n"
            f"[Input]\n{stdin}\n\n"
            f"[Expected Output]\n{expected}")


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
