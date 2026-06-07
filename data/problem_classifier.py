"""
Problem-tag classification for PIE samples.

For each `problem_id`, returns one tag from a fixed taxonomy describing the
algorithmic category of the problem (`dp`, `graph`, etc.). Uses the FULL
natural-language problem statement from
`pie-perf/data/problem_statements_translated.zip`.

Lookups are cached on disk in `data/problem_tags_<classifier_id>.csv` so the
LLM is only invoked once per (problem_id, classifier_id) pair across runs.
Switching the classifier is one parameter change; the old cache file stays
preserved as a separate file.

Usage:
    from data.problem_classifier import classify_problem
    tag = classify_problem("p03146")    # "dp"
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
    "dp", "graph", "tree", "string", "math", "geometry",
    "greedy", "simulation", "data_structure", "search",
    "combinatorial", "other",
]

# Prompt v2 — statement-first ordering, minimal examples (more examples seem
# to confuse Qwen-7B under greedy decoding).
_CLASSIFIER_PROMPT_V2 = """Categorise this competitive-programming problem.

Statement:
{statement}

What is the primary algorithmic technique? Reply with ONE word from:
math, dp, graph, tree, string, geometry, greedy, simulation, data_structure, search, combinatorial, other.

Examples:
- "Compute GCD(a,b) modulo p" -> math
- "Find shortest path between two cities" -> graph
- "Count number of ways to make change for N" -> dp
- "Simulate a queue processing tasks" -> simulation
- "Find a substring in S that matches pattern P" -> string

Answer:"""



def _cache_path(classifier_id: str) -> str:
    return os.path.join(_HERE, f"problem_tags_{classifier_id}.csv")


def _load_cache(path: str) -> dict:
    cache = {}
    if not os.path.exists(path):
        return cache
    with open(path) as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0 and row and row[0] == "problem_id":
                continue        # header
            if len(row) >= 2:
                cache[row[0]] = row[1]
    return cache


def _append_cache(path: str, problem_id: str, tag: str):
    is_new = not os.path.exists(path)
    with open(path, "a") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["problem_id", "tag"])
        w.writerow([problem_id, tag])


def _extract_tag(raw: str) -> str:
    """
    Find the first taxonomy word in the model's free-form output.
    Falls back to 'other' if no recognised tag is found.
    """
    lower = raw.lower()
    # Strip non-word characters at the start for robustness
    lower = re.sub(r"^[^a-z]+", "", lower)
    for tag in TAXONOMY:
        # Match the tag as a whole word at the start, or anywhere as a fallback
        if re.match(rf"\b{re.escape(tag)}\b", lower):
            return tag
    for tag in TAXONOMY:
        if re.search(rf"\b{re.escape(tag)}\b", lower):
            return tag
    return "other"


def _local_classifier_fn(statement: str) -> str:
    """Default classifier: few-shot with the already-loaded local model.

    Statement is truncated to 1000 chars; in practice longer context made
    the 7B model less reliable on this short-output task.
    """
    from local_llm import quick_inference
    prompt = _CLASSIFIER_PROMPT_V2.format(statement=statement[:1000])
    return quick_inference(prompt, max_new_tokens=12)


_inmem_cache = {}     # {classifier_id: {problem_id: tag}}


def classify_problem(problem_id: str,
                     classifier_id: str = "qwen7b_v2",
                     classifier_fn: Optional[Callable[[str], str]] = None,
                     ) -> str:
    """
    Return one tag from TAXONOMY for `problem_id`. Hits the disk cache for
    `classifier_id` first; on miss, fetches the FULL problem statement and
    invokes `classifier_fn(statement)` (default: local Qwen zero-shot).

    Each classifier_id has its own cache file
    (`data/problem_tags_<classifier_id>.csv`), so swapping classifiers
    preserves prior tags and writes new ones independently.

    Tags are persisted incrementally; even a crash mid-run keeps the
    classifications done so far.
    """
    path = _cache_path(classifier_id)
    cache = _inmem_cache.setdefault(classifier_id, _load_cache(path))
    if problem_id in cache:
        return cache[problem_id]

    # Lazy import to avoid a circular dep at module load time
    from data.pie_loader import get_problem_statement
    statement = get_problem_statement(problem_id, constraints_only=False,
                                       max_chars=3000)
    if not statement:
        tag = "unknown"
    else:
        fn = classifier_fn or _local_classifier_fn
        try:
            tag = _extract_tag(fn(statement))
        except Exception as e:
            print(f"[classify_problem] {problem_id} failed: {e}")
            tag = "unknown"

    cache[problem_id] = tag
    _append_cache(path, problem_id, tag)
    return tag


def get_cache(classifier_id: str = "qwen7b_v2") -> dict:
    """Read the on-disk cache for a given classifier as a {problem_id: tag} dict."""
    return _load_cache(_cache_path(classifier_id))


if __name__ == "__main__":
    # Quick smoke test from the CLI
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_ids", nargs="+",
                    help="One or more problem ids, e.g. p03146 p00465")
    ap.add_argument("--classifier-id", default="qwen7b_v2")
    args = ap.parse_args()
    for pid in args.problem_ids:
        tag = classify_problem(pid, classifier_id=args.classifier_id)
        print(f"{pid}: {tag}")
