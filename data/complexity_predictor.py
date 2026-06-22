"""
LLM-based time complexity classification for PIE samples.

Mirrors `data/problem_classifier.py` but classifies a piece of C++ source
into one of a fixed Big-O taxonomy. Uses the same local model that does the
optimisation (default: Qwen2.5-Coder-7B-Instruct) via
`local_llm.quick_inference`.

Per-predictor disk cache lives at `data/code_complexity_<predictor_id>.csv`,
keyed by sample_id. Switching predictor versions (different prompt, different
model) writes to a new cache file; old caches are preserved as audit trail.

Usage:
    from data.complexity_predictor import predict_complexity
    info = predict_complexity("pie_p02695_s405258011", slow_cpp_source)
    # -> {"complexity": "O(n^2)", "raw": "<label>O(n^2)</label>", "predictor_id": "qwen7b_v2"}
"""
import csv
import os
import re
import sys
from typing import Optional, Callable

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)


TAXONOMY = [
    "O(1)", "O(log n)", "O(n)", "O(n log n)",
    "O(n^2)", "O(n^2 log n)", "O(n^3)", "O(2^n)",
    "unknown",
]

# Prompt v1 — code-first, few-shot, single-token output. The taxonomy is
# listed in increasing-complexity order so the model has a clear ordinal scale.
_COMPLEXITY_PROMPT_V1 = """Estimate the time complexity of the following C++ program.

```cpp
{code}
```

Reply with EXACTLY ONE label from this taxonomy:
O(1), O(log n), O(n), O(n log n), O(n^2), O(n^2 log n), O(n^3), O(2^n), unknown.

Examples:
- `for(i=0;i<n;i++) sum += a[i];`                          -> O(n)
- `for(i=0;i<n;i++) for(j=0;j<n;j++) ...`                  -> O(n^2)
- `while (n > 0) n /= 2;`                                  -> O(log n)
- `sort(a.begin(), a.end());`                              -> O(n log n)
- recursive Fibonacci with no memoisation                  -> O(2^n)
- DP with an n*m table where both n,m <= N                -> O(n^2)
- `for(i=0;i<n;i++) sort(a.begin(),a.end());`              -> O(n^2 log n)
- three nested for-loops each running up to n              -> O(n^3)

Consider the DOMINANT loop, recursion depth, and any STL/sort/search inside
loops. Output the SINGLE WORST-CASE complexity label, nothing else.

Answer:"""


# Prompt v2 — same few-shot core, but forces the answer into <label>...</label>
# tags so the chat-tuned model can preface freely without breaking extraction.
_COMPLEXITY_PROMPT_V2 = """You will estimate the worst-case time complexity of a C++ program.

```cpp
{code}
```

Allowed labels (pick EXACTLY ONE):
O(1), O(log n), O(n), O(n log n), O(n^2), O(n^2 log n), O(n^3), O(2^n), unknown.

Quick reference:
- single pass over n elements                          -> O(n)
- two nested loops each up to n                        -> O(n^2)
- three nested loops each up to n                      -> O(n^3)
- halving / doubling in a single loop                  -> O(log n)
- sort(...) call or merge/quick/heap sort              -> O(n log n)
- sort inside a single loop                            -> O(n^2 log n)
- naive recursion with branching factor > 1, no memo   -> O(2^n)
- only a fixed number of operations regardless of n    -> O(1)

Consider the DOMINANT loop, recursion depth, and any STL sort/search inside
loops. Output ONLY the label, wrapped in tags, like this:
<label>O(n^2)</label>

<label>"""


def _cache_path(predictor_id: str) -> str:
    return os.path.join(_HERE, f"code_complexity_{predictor_id}.csv")


def _load_cache(path: str) -> dict:
    cache = {}
    if not os.path.exists(path):
        return cache
    with open(path) as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0 and row and row[0] == "sample_id":
                continue       # header
            if len(row) >= 2:
                cache[row[0]] = row[1]
    return cache


def _append_cache(path: str, sample_id: str, complexity: str):
    is_new = not os.path.exists(path)
    with open(path, "a") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["sample_id", "complexity"])
        w.writerow([sample_id, complexity])


_UNICODE_FIXES = {
    "²": "^2", "³": "^3", "⁴": "^4", "ⁿ": "^n",
    "×": "*", "·": "*", "≤": "<=", "≥": ">=",
    "—": " ", "–": " ",
}

# Natural-language synonyms, scanned only after literal-label matching fails.
# Ordered by specificity — "linearithmic" must beat "linear".
_NL_SYNONYMS = [
    ("linearithmic",  "O(n log n)"),
    ("quasi-linear",  "O(n log n)"),
    ("n log n",       "O(n log n)"),
    ("n*log",         "O(n log n)"),
    ("logarithmic",   "O(log n)"),
    ("log n",         "O(log n)"),
    ("quadratic",     "O(n^2)"),
    ("cubic",         "O(n^3)"),
    ("exponential",   "O(2^n)"),
    ("linear",        "O(n)"),
    ("constant",      "O(1)"),
]


def _normalise(raw: str) -> str:
    """Strip markdown/unicode noise so substring matching catches more forms."""
    s = raw
    for k, v in _UNICODE_FIXES.items():
        s = s.replace(k, v)
    # Strip common markdown punctuation that surrounds the label.
    for ch in ("`", "*", "$", "\\", "_"):
        s = s.replace(ch, "")
    # Drop spaces and lower-case so "O ( n^2 )" / "O(N^2)" both match.
    return s.replace(" ", "").lower()


def _extract_label(raw: str) -> str:
    """
    Find the first taxonomy label in the model's free-form output.

    Tries, in order:
      1. Content inside <label>...</label> tags (the v2 prompt asks for this).
      2. Literal taxonomy substring match (e.g. 'O(n^2 log n)') after
         unicode/markdown normalisation.
      3. Natural-language synonym fallback (e.g. 'quadratic' -> O(n^2)).
    """
    if not raw:
        return "unknown"

    # 1. Prefer content inside <label>...</label>
    m = re.search(r"<label>\s*(.*?)\s*</label>", raw, flags=re.DOTALL | re.IGNORECASE)
    payload = m.group(1) if m else raw

    cleaned = _normalise(payload)
    # 2. Substring match against taxonomy, longest-first (so 'O(n^2 log n)'
    # wins over 'O(n^2)').
    for label in sorted(TAXONOMY, key=lambda s: -len(s)):
        if label == "unknown":
            continue
        key = label.replace(" ", "").lower()
        if key in cleaned:
            return label

    # 3. Natural-language fallback — scan the original payload (case-insensitive)
    # so multi-word synonyms like 'n log n' aren't destroyed by space stripping.
    payload_lc = payload.lower()
    for needle, label in _NL_SYNONYMS:
        if needle in payload_lc:
            return label

    return "unknown"


def _local_predictor_fn(source: str) -> str:
    """Default predictor: few-shot with <label>...</label> output gating."""
    from local_llm import quick_inference
    # Cap the source to keep the prompt tight; the model only needs to see
    # the structure, not every line of trivial bookkeeping.
    prompt = _COMPLEXITY_PROMPT_V2.format(code=source[:4000])
    # 64 tokens leaves room for preamble + the tagged label without runaway.
    return quick_inference(prompt, max_new_tokens=64)


_inmem_cache = {}    # {predictor_id: {sample_id: complexity}}


def predict_complexity(sample_id: str,
                       source_code: str,
                       predictor_id: str = "qwen7b_v2",
                       predictor_fn: Optional[Callable[[str], str]] = None,
                       ) -> dict:
    """
    Return {"complexity": <one of TAXONOMY>, "predictor_id": ..., "raw": ...}
    for the given source code. Hits the disk cache for `predictor_id` first;
    on miss invokes `predictor_fn(source_code)` (default: local Qwen zero/few-shot).
    """
    path = _cache_path(predictor_id)
    cache = _inmem_cache.setdefault(predictor_id, _load_cache(path))
    if sample_id in cache:
        return {"complexity": cache[sample_id], "predictor_id": predictor_id,
                "raw": cache[sample_id], "cached": True}

    if not source_code or not source_code.strip():
        complexity = "unknown"
        raw = ""
    else:
        fn = predictor_fn or _local_predictor_fn
        try:
            raw = fn(source_code)
            complexity = _extract_label(raw)
        except Exception as e:
            print(f"[predict_complexity] {sample_id} failed: {e}")
            complexity = "unknown"
            raw = ""

    cache[sample_id] = complexity
    _append_cache(path, sample_id, complexity)
    return {"complexity": complexity, "predictor_id": predictor_id,
            "raw": raw, "cached": False}


def get_cache(predictor_id: str = "qwen7b_v2") -> dict:
    """Read the on-disk cache as a {sample_id: complexity} dict."""
    return _load_cache(_cache_path(predictor_id))


if __name__ == "__main__":
    # Quick CLI smoke test
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictor-id", default="qwen7b_v2")
    ap.add_argument("--source-file", help="Path to a .cpp file to classify")
    ap.add_argument("--sample-id", default=None,
                    help="Cache key (defaults to filename stem)")
    args = ap.parse_args()
    if not args.source_file:
        ap.error("provide --source-file")
    src = open(args.source_file).read()
    sid = args.sample_id or os.path.splitext(os.path.basename(args.source_file))[0]
    info = predict_complexity(sid, src, predictor_id=args.predictor_id)
    print(f"{sid}: {info['complexity']}  (raw={info['raw']!r})")
