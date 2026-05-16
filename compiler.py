"""
Compile a C++ source string, run it, and return stdout + exit code.
Also supports gprof profiling output capture.
"""
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from config import (
    CXX, CXX_FLAGS_DEBUG, CXX_FLAGS_BENCH, COMPILE_TIMEOUT, RUN_TIMEOUT,
    WORKSPACE_DIR, PIE_NUM_TRIALS, PIE_IGNORE_FIRST, PIE_RUN_TIMEOUT,
    PIE_TASKSET_CPU,
)


class CompileResult:
    def __init__(self, success, binary_path, stderr, source_path):
        self.success = success
        self.binary_path = binary_path
        self.stderr = stderr          # compiler error/warning text
        self.source_path = source_path


class RunResult:
    def __init__(self, stdout, stderr, returncode, timed_out):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.timed_out = timed_out
        self.passed = False           # set externally after output comparison


def compile_code(source: str, name: str, use_bench_flags=False) -> CompileResult:
    """Write source to a temp dir, compile, return CompileResult."""
    work_dir = os.path.join(WORKSPACE_DIR, name)
    os.makedirs(work_dir, exist_ok=True)

    src_path = os.path.join(work_dir, f"{name}.cpp")
    bin_path = os.path.join(work_dir, f"{name}.bin")

    with open(src_path, "w") as f:
        f.write(source)

    flags = CXX_FLAGS_BENCH if use_bench_flags else CXX_FLAGS_DEBUG
    # Remove -fsanitize on bench runs to get clean gprof output
    if use_bench_flags:
        flags = [f for f in flags if "sanitize" not in f]

    cmd = [CXX] + flags + [src_path, "-o", bin_path]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
        success = proc.returncode == 0
        return CompileResult(success, bin_path if success else None,
                             proc.stderr, src_path)
    except subprocess.TimeoutExpired:
        return CompileResult(False, None, "Compilation timed out", src_path)
    except Exception as e:
        return CompileResult(False, None, str(e), src_path)


def run_binary(binary_path: str, stdin_data: str = "", capture_gprof=False) -> RunResult:
    """Run a compiled binary and return its output."""
    work_dir = os.path.dirname(binary_path)
    env = os.environ.copy()
    env["GMON_OUT_PREFIX"] = os.path.join(work_dir, "gmon")

    stdin_bytes = (stdin_data.encode("utf-8", errors="replace")
                   if isinstance(stdin_data, str) else (stdin_data or b""))
    try:
        proc = subprocess.run(
            [binary_path],
            input=stdin_bytes,
            capture_output=True,
            text=False,
            timeout=RUN_TIMEOUT,
            env=env,
            cwd=work_dir,
        )
        stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
        result = RunResult(stdout, stderr, proc.returncode, False)
    except subprocess.TimeoutExpired:
        result = RunResult("", "Timed out", -1, True)

    return result


def compile_and_run(source: str, name: str, expected_output: str = None,
                    use_bench_flags=False) -> dict:
    """
    Compile source, run it, optionally check output.
    Returns a summary dict consumed by the pipeline.
    """
    cr = compile_code(source, name, use_bench_flags=use_bench_flags)
    if not cr.success:
        return {
            "compiled": False,
            "compile_error": cr.stderr,
            "ran": False,
            "passed": False,
            "stdout": "",
            "binary_path": None,
            "source_path": cr.source_path,
        }

    rr = run_binary(cr.binary_path)
    passed = False
    if expected_output is not None and not rr.timed_out:
        passed = rr.stdout.strip() == expected_output.strip()

    return {
        "compiled": True,
        "compile_error": cr.stderr,   # may contain warnings
        "ran": not rr.timed_out and rr.returncode == 0,
        "passed": passed,
        "stdout": rr.stdout,
        "returncode": rr.returncode,
        "binary_path": cr.binary_path,
        "source_path": cr.source_path,
    }


def _normalize_output(s: str) -> str:
    """Whitespace-tolerant: strip + rstrip per line + drop trailing blank lines."""
    lines = [line.rstrip() for line in s.strip().splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _tokens_match(a: str, b: str, rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> bool:
    """
    Token-by-token comparison after whitespace normalisation. Numeric tokens
    compare with a relative+absolute tolerance so that '5.5' and '5.5000000000'
    are considered equal (CodeNet's judge does this for many problems).
    """
    a_tokens = _normalize_output(a).split()
    b_tokens = _normalize_output(b).split()
    if len(a_tokens) != len(b_tokens):
        return False
    for x, y in zip(a_tokens, b_tokens):
        if x == y:
            continue
        try:
            xf, yf = float(x), float(y)
        except ValueError:
            return False
        if abs(xf - yf) > max(abs_tol, rel_tol * max(abs(xf), abs(yf))):
            return False
    return True


def _run_timed_once(binary_path: str, stdin_data: str, timeout: int,
                    taskset_cpu=None) -> tuple:
    """Run binary once, return (stdout, returncode, elapsed_s, timed_out).

    Runs in binary mode and decodes stdout with errors='replace' so that a
    program emitting non-UTF-8 bytes (which counts as wrong output anyway)
    doesn't crash the pipeline.
    """
    cmd = [binary_path]
    if taskset_cpu is not None:
        cmd = ["taskset", "-c", str(taskset_cpu)] + cmd
    work_dir = os.path.dirname(binary_path)
    env = os.environ.copy()
    env["GMON_OUT_PREFIX"] = os.path.join(work_dir, "gmon")
    stdin_bytes = (stdin_data.encode("utf-8", errors="replace")
                   if isinstance(stdin_data, str) else (stdin_data or b""))
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, input=stdin_bytes, capture_output=True, text=False,
            timeout=timeout, env=env, cwd=work_dir,
        )
        elapsed = time.perf_counter() - t0
        stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
        return stdout, proc.returncode, elapsed, False
    except subprocess.TimeoutExpired:
        return "", -1, timeout, True


def compile_and_run_tests(source: str, name: str, test_cases: list,
                          num_trials: int = PIE_NUM_TRIALS,
                          ignore_first_k: int = PIE_IGNORE_FIRST,
                          timeout: int = PIE_RUN_TIMEOUT,
                          taskset_cpu=PIE_TASKSET_CPU,
                          use_bench_flags: bool = False) -> dict:
    """
    Compile once, then run the binary against each test case `num_trials` times
    (skipping the first `ignore_first_k` warmup runs). Each test case is a dict
    with keys 'input' (stdin str) and 'expected_output' (expected stdout str).

    Returns:
      {
        compiled: bool,
        passed:   bool,                 # ALL test cases produced correct output
        per_test: [                     # one entry per test case
          { idx, passed, stdout, mean_ms, std_ms, timed_out, returncode }
        ],
        mean_ms: float,                 # overall mean across kept trials
        median_ms: float,
        binary_path, source_path, compile_error, ...
      }
    """
    cr = compile_code(source, name, use_bench_flags=use_bench_flags)
    if not cr.success:
        return {
            "compiled": False, "passed": False, "failure_mode": "compile",
            "per_test": [], "mean_ms": None, "median_ms": None,
            "compile_error": cr.stderr, "binary_path": None,
            "source_path": cr.source_path,
        }

    per_test = []
    all_kept_times = []
    all_passed = True
    for idx, tc in enumerate(test_cases):
        stdin_data = tc.get("input", "")
        expected   = tc.get("expected_output", "")
        kept_times_ms = []
        last_stdout = ""
        last_rc = 0
        timed_out_any = False
        tc_passed = False
        for trial in range(num_trials + ignore_first_k):
            stdout, rc, elapsed, timed_out = _run_timed_once(
                cr.binary_path, stdin_data, timeout, taskset_cpu=taskset_cpu,
            )
            if timed_out:
                timed_out_any = True
                break
            last_stdout, last_rc = stdout, rc
            if trial >= ignore_first_k:
                kept_times_ms.append(elapsed * 1000.0)
            # Cheap correctness check on first non-warmup trial
            if trial == ignore_first_k and rc == 0:
                tc_passed = _tokens_match(stdout, expected)
                if not tc_passed:
                    break  # don't waste trials timing a wrong answer

        if not tc_passed or timed_out_any or last_rc != 0:
            all_passed = False

        if timed_out_any:
            tc_fail_mode = "timeout"
        elif last_rc != 0:
            tc_fail_mode = "runtime_error"
        elif not tc_passed:
            tc_fail_mode = "wrong_output"
        else:
            tc_fail_mode = None

        mean_ms = statistics.mean(kept_times_ms) if kept_times_ms else None
        std_ms  = statistics.pstdev(kept_times_ms) if len(kept_times_ms) > 1 else 0.0
        per_test.append({
            "idx": idx,
            "passed": tc_passed,
            "stdout": last_stdout[:500],
            "expected": expected[:500],
            "mean_ms": round(mean_ms, 3) if mean_ms is not None else None,
            "std_ms":  round(std_ms, 3),
            "timed_out": timed_out_any,
            "returncode": last_rc,
            "failure_mode": tc_fail_mode,
        })
        all_kept_times.extend(kept_times_ms)

    overall_mean   = statistics.mean(all_kept_times)   if all_kept_times else None
    overall_median = statistics.median(all_kept_times) if all_kept_times else None

    # Aggregate failure mode: priority timeout > runtime_error > wrong_output
    fail_modes = [t["failure_mode"] for t in per_test if t["failure_mode"]]
    if all_passed:
        run_fail_mode = None
    elif "timeout" in fail_modes:
        run_fail_mode = "timeout"
    elif "runtime_error" in fail_modes:
        run_fail_mode = "runtime_error"
    else:
        run_fail_mode = "wrong_output"

    return {
        "compiled": True,
        "passed": all_passed,
        "failure_mode": run_fail_mode,
        "per_test": per_test,
        "mean_ms":   round(overall_mean,   3) if overall_mean   is not None else None,
        "median_ms": round(overall_median, 3) if overall_median is not None else None,
        "compile_error": cr.stderr,
        "binary_path": cr.binary_path,
        "source_path": cr.source_path,
    }
