"""Central configuration for the Profile-Guided Code Correction pipeline."""
import os, sys

# ── Extra Python packages (optional shared install dir) ───────────────────────
# Allow an out-of-tree package directory via PROJECT_PKG_DIR env var. Useful
# on managed clusters where a shared partition holds the heavy deps (torch,
# transformers, bitsandbytes) outside the home quota. No-op on machines that
# don't set the variable or where the path doesn't exist — packages are then
# expected to come from the active virtualenv (see README §1.3).
_PKG_DIR = os.environ.get("PROJECT_PKG_DIR", "")
if _PKG_DIR and os.path.isdir(_PKG_DIR) and _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

# ── LLM ──────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = "claude-haiku-4-5-20251001"   # cheap & fast for experiments
LLM_MAX_TOKENS = 2048
LLM_TEMPERATURE = 0.0                     # deterministic for reproducibility

# ── Compilation ───────────────────────────────────────────────────────────────
CXX = "g++"
CXX_FLAGS_DEBUG  = ["-O0", "-g", "-pg", "-std=c++17"]
CXX_FLAGS_BENCH  = ["-O2", "-g", "-pg", "-std=c++17"]
COMPILE_TIMEOUT  = 30   # seconds

# ── Profiling ─────────────────────────────────────────────────────────────────
RUN_TIMEOUT      = 15   # seconds per test run
PERF_EVENTS      = "cycles,instructions,cache-misses,branch-misses"
USE_PERF         = True   # set False if perf requires privileges on this host

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(__file__)
DATA_DIR      = os.path.join(BASE_DIR, "data")
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
RESULTS_DIR   = os.path.join(BASE_DIR, "results")

# ── Dataset ───────────────────────────────────────────────────────────────────
DEFECTS4C_JSONL_URL = (
    "https://raw.githubusercontent.com/defects4c/defects4c/master"
    "/defectsc_tpl/data/single_function_allinone.saved.jsonl"
)
SAMPLE_CACHE = os.path.join(DATA_DIR, "samples_cache.jsonl")

# ── PIE (Performance-Improving Edits, IBM CodeNet) ────────────────────────────
PIE_BASE          = os.path.join(BASE_DIR, "pie-perf", "data")
PIE_SPLIT_TEST    = os.path.join(PIE_BASE, "cpp_splits", "test.jsonl")
PIE_SPLIT_VAL     = os.path.join(PIE_BASE, "cpp_splits", "val.jsonl")
PIE_TESTCASES_DIR        = os.path.join(PIE_BASE, "public_test_cases")
# Larger merged_test_cases.tar.gz set from the PIE website. If present we
# prefer it (much denser per-problem coverage; ~100 tests vs ~2 for some
# problems) and fall back to public_test_cases per-problem when missing.
PIE_MERGED_TESTCASES_DIR = os.path.join(PIE_BASE, "merged_test_cases")

# ── Timing (used for PIE speedup measurement) ─────────────────────────────────
PIE_NUM_TRIALS   = 3      # runs per test case after warmup
PIE_IGNORE_FIRST = 1      # warmup runs to discard
PIE_RUN_TIMEOUT  = 10     # seconds per single execution
PIE_TASKSET_CPU  = 0      # pin all timed runs to this CPU (None to disable)
