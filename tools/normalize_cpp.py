#!/usr/bin/env python3
"""
Normalize C++ source for cleaner diffs.

Used by `pipeline.py` when computing `*_vs_v0.diff` and `oracle_v0_to_v1.diff`
artifacts inside each run_<timestamp>/ directory.

Primary path: run the source through `clang-format` with the LLVM style and
empty lines suppressed. This canonicalises both inter- and intra-line
whitespace (e.g. `vector<int>x;` becomes `vector<int> x;` consistently on
both sides of a diff).

Fallback path (if clang-format is missing or fails): a pure-Python
normalisation pass that only handles inter-line whitespace.

Both paths finish with:
  - Tabs converted to spaces
  - Trailing whitespace stripped on every line
  - All blank lines dropped
  - Exactly one trailing newline

Aggressive but appropriate for diff visualisation: the original code is
preserved on disk in `v0_*.cpp` and `candidate_*.cpp`; only the diff files
are computed on the normalised text.

CLI:
    python3 tools/normalize_cpp.py path/to/file.cpp           # prints to stdout
    python3 tools/normalize_cpp.py path/to/file.cpp -i        # rewrites in place
    cat foo.cpp | python3 tools/normalize_cpp.py              # from stdin
    python3 tools/normalize_cpp.py --no-clang-format ...      # skip clang-format
"""
import argparse
import shutil
import subprocess
import sys
from typing import Optional


CLANG_FORMAT_STYLE = (
    "{BasedOnStyle: LLVM, "
    "MaxEmptyLinesToKeep: 0, "
    "ColumnLimit: 0, "                # don't reflow long lines (preserves intent)
    "SortIncludes: false, "           # don't reorder #include lines
    "IndentWidth: 4, "
    "UseTab: Never}"
)


def _post_clean(source: str) -> str:
    """Final pass shared by both clang-format and pure-Python paths."""
    if not source:
        return ""
    lines = source.split("\n")
    detabbed = []
    for line in lines:
        n_lead = 0
        while n_lead < len(line) and line[n_lead] == "\t":
            n_lead += 1
        detabbed.append("    " * n_lead + line[n_lead:])
    stripped = [l.rstrip() for l in detabbed]
    nonblank = [l for l in stripped if l]
    return "\n".join(nonblank) + "\n"


def _clang_format(source: str, timeout: int = 5) -> Optional[str]:
    """Run clang-format with the canonical style. Returns None on failure."""
    if shutil.which("clang-format") is None:
        return None
    try:
        proc = subprocess.run(
            ["clang-format", f"--style={CLANG_FORMAT_STYLE}",
             "--assume-filename=src.cpp"],
            input=source, capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def normalize_cpp(source: str, use_clang_format: bool = True) -> str:
    """
    Canonicalise whitespace in a C++ source string.

    With `use_clang_format=True` (default), pipes through clang-format with a
    fixed style, then strips blank lines. Falls back to pure-Python normalisation
    if clang-format is unavailable.
    """
    if not source:
        return ""
    if use_clang_format:
        formatted = _clang_format(source)
        if formatted is not None:
            return _post_clean(formatted)
    return _post_clean(source)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="C++ file (omit to read stdin)")
    ap.add_argument("-i", "--in-place", action="store_true",
                    help="Rewrite the file in place instead of printing")
    ap.add_argument("--no-clang-format", action="store_true",
                    help="Skip clang-format (pure-Python pass only)")
    args = ap.parse_args()

    if args.path:
        with open(args.path) as f:
            src = f.read()
    else:
        src = sys.stdin.read()

    out = normalize_cpp(src, use_clang_format=not args.no_clang_format)

    if args.in_place and args.path:
        with open(args.path, "w") as f:
            f.write(out)
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
