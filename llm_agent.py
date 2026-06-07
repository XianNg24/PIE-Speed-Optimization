"""
LLM-based code repair agent.

Three modes:
  static    – passes only the buggy source code to the LLM
  dynamic   – adds runtime output diff (Actual vs Expected) only
  profiling – adds runtime output diff + gprof + perf counters
"""
import re
import anthropic
from config import ANTHROPIC_API_KEY, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE

_client = None


def _get_client():
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it with: export ANTHROPIC_API_KEY=sk-ant-..."
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


SYSTEM_PROMPTS = {
    "repair": (
        "You are an expert C/C++ software engineer specialising in bug repair. "
        "When given a buggy function or program, return ONLY the corrected source "
        "code inside a single ```cpp ... ``` fenced block — no explanation, no preamble."
    ),
    "optimize": (
        "You are an expert C/C++ software engineer specialising in performance "
        "optimisation. When given a correct but slow program, return ONLY a faster "
        "version that produces IDENTICAL stdout for every possible input, inside a "
        "single ```cpp ... ``` fenced block — no explanation, no preamble. "
        "Preserve all observable behaviour exactly. Do NOT change the I/O format."
    ),
}

_USER_PREAMBLES = {
    "repair": ("The following C++ program contains one or more bugs. "
               "Fix every bug and return the complete corrected source."),
    "optimize": ("The following C++ program is correct but slow. Produce a "
                 "strictly faster version that preserves identical observable "
                 "behaviour on every test case."),
}


_OPTIMIZE_RULES_FOOTER = (
    "Optimization Rules:\n"
    "- Encapsulate the optimized code within a C++ code block "
    "(i.e., ```cpp\\n[Your Code Here]\\n```).\n"
    "- Preserve identical stdout for EVERY test case (not only the one shown).\n"
    "- Do NOT change the I/O format.\n"
    "- Focus solely on performance optimization; correctness is non-negotiable.\n"
    "- Do not include test driver code or explanatory preamble."
)
_REPAIR_RULES_FOOTER = (
    "Rules:\n"
    "- Encapsulate the fixed code within a C++ code block.\n"
    "- Return the complete corrected source — not a diff.\n"
    "- No explanation outside the fenced block."
)


def _build_user_message(buggy_code: str, feedback: str = None,
                        task_type: str = "repair",
                        problem_statement: str = None,
                        test_case_block: str = None,
                        tag_advice: str = None,
                        complexity_hint: str = None) -> str:
    """EffiLearner-style section layout for the user message."""
    preamble = _USER_PREAMBLES.get(task_type, _USER_PREAMBLES["repair"])
    parts = [preamble]
    if problem_statement:
        parts.append(f"Task Description:\n{problem_statement.strip()}")
    if test_case_block:
        parts.append(test_case_block.strip())
    parts.append(f"Original Code:\n```cpp\n{buggy_code.strip()}\n```")
    if feedback:
        parts.append(feedback.strip())
    if complexity_hint:
        parts.append(complexity_hint.strip())
    if tag_advice:
        parts.append(tag_advice.strip())
    parts.append(_OPTIMIZE_RULES_FOOTER if task_type == "optimize"
                 else _REPAIR_RULES_FOOTER)
    return "\n\n".join(parts)


def _extract_code(response_text: str) -> str:
    """Pull the first ```cpp ... ``` or ``` ... ``` block from the LLM reply."""
    # Try ```cpp first, then ``` fallback
    for pattern in [r"```cpp\s*(.*?)```", r"```c\s*(.*?)```", r"```\s*(.*?)```"]:
        m = re.search(pattern, response_text, re.DOTALL)
        if m:
            return m.group(1).strip()
    # No fence found – return the whole reply trimmed
    return response_text.strip()


def repair(buggy_code: str, feedback: str = None, mode: str = "static",
           k: int = 1, temperature: float = 0.6, top_p: float = 0.95,
           seed: int = 0, task_type: str = "repair",
           problem_statement: str = None,
           test_case_block: str = None,
           tag_advice: str = None,
           complexity_hint: str = None) -> dict:
    """
    Call the LLM to repair the buggy code.

    k=1  -> single deterministic call (uses LLM_TEMPERATURE from config).
    k>1  -> k sampled calls, returns k candidates in `candidates`.
    """
    client = _get_client()
    user_msg = _build_user_message(buggy_code, feedback, task_type=task_type,
                                    problem_statement=problem_statement,
                                    test_case_block=test_case_block,
                                    tag_advice=tag_advice,
                                    complexity_hint=complexity_hint)
    sys_prompt = SYSTEM_PROMPTS.get(task_type, SYSTEM_PROMPTS["repair"])

    candidates = []
    in_tokens = 0
    used_temp = LLM_TEMPERATURE if k == 1 else temperature
    for _ in range(k):
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            temperature=used_temp,
            top_p=top_p if k > 1 else 1.0,
            system=sys_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text
        candidates.append({
            "fixed_code": _extract_code(raw),
            "raw_response": raw,
            "completion_tokens": response.usage.output_tokens,
        })
        in_tokens = response.usage.input_tokens

    return {
        "mode": mode,
        "k": k,
        "temperature": used_temp,
        "fixed_code": candidates[0]["fixed_code"],          # back-compat
        "raw_response": candidates[0]["raw_response"],      # back-compat
        "completion_tokens": candidates[0]["completion_tokens"],
        "candidates": candidates,
        "prompt_tokens": in_tokens,
        "prompt_messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": user_msg},
        ],
    }


def repair_static(buggy_code: str, **kw) -> dict:
    return repair(buggy_code, feedback=None, mode="static", **kw)


def repair_dynamic(buggy_code: str, runtime_feedback: str, **kw) -> dict:
    """Runtime output diff only — no gprof / perf."""
    return repair(buggy_code, feedback=runtime_feedback, mode="dynamic", **kw)


def repair_profiling(buggy_code: str, profile_summary: str, **kw) -> dict:
    """Runtime output diff + gprof + perf counters."""
    return repair(buggy_code, feedback=profile_summary, mode="profiling", **kw)
