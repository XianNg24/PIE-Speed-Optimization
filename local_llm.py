"""
Local LLM inference via HuggingFace transformers.
Drop-in replacement for llm_agent.py when no Anthropic API key is available.

Usage:
    python local_llm.py           # runs a quick self-test on sample 001
    python pipeline.py --backend local --samples 2 --mode both
"""
import os
import re
import sys
import time

# Add the project's Python package directory to sys.path
_PKG_DIR = "/cs/student/project_msc/2025/dsml/nmxian/py_packages"
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

# HuggingFace cache: respect the user's env vars if set, otherwise fall
# back to ~/.cache/huggingface (the HF library's own default). The previous
# hard-coded path was UCL-cluster-specific and broke on other machines.
HF_CACHE = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
os.environ.setdefault("HF_HOME", HF_CACHE)
os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(HF_CACHE, "hub"))

DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"

# Module-level cache so the model is only loaded once per process
_model = None
_tokenizer = None
_loaded_model_name = None


def load_model(model_name: str = DEFAULT_MODEL, force_4bit: bool = False):
    """
    Load model + tokenizer into GPU. Called lazily on first inference.

    force_4bit=True overrides the free-VRAM heuristic and quantises to NF4
    regardless. Useful when sharing the GPU or running a configuration
    (larger k, longer prompts) that the heuristic underestimates.
    """
    global _model, _tokenizer, _loaded_model_name
    if _loaded_model_name == model_name:
        return

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    except ImportError as e:
        raise ImportError(
            f"Required packages missing: {e}\n"
            "Install with: pip3 install torch transformers accelerate bitsandbytes --user"
        )

    print(f"[local_llm] Loading {model_name} ...", flush=True)
    t0 = time.time()

    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
        cache_dir=os.environ["TRANSFORMERS_CACHE"],
    )

    # Use fp16 if the model fits; fall back to 4-bit NF4 if VRAM is tight.
    # Use mem_get_info() which accounts for ALL processes, not just this one.
    free_vram_gb = 0
    if torch.cuda.is_available():
        free_bytes, _ = torch.cuda.mem_get_info(0)
        free_vram_gb = free_bytes / 1024 ** 3

    use_4bit = force_4bit or free_vram_gb < 15

    if use_4bit:
        reason = "forced" if force_4bit else f"free VRAM {free_vram_gb:.1f} GB < 15 GB"
        print(f"[local_llm] using 4-bit NF4 quantisation ({reason})")
        bnb_cfg = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=bnb_cfg,
            device_map="auto",
            trust_remote_code=True,
            cache_dir=os.environ["TRANSFORMERS_CACHE"],
        )
    else:
        print(f"[local_llm] Free VRAM {free_vram_gb:.1f} GB → using fp16")
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True,
            cache_dir=os.environ["TRANSFORMERS_CACHE"],
        )

    model.eval()
    print(f"[local_llm] Loaded in {time.time()-t0:.1f}s")
    _model = model
    _tokenizer = tokenizer
    _loaded_model_name = model_name


def clear_cuda_cache():
    """
    Release cached CUDA memory between modes / samples. Reclaims the
    'reserved but unallocated' fragment pool PyTorch keeps for reuse,
    which can otherwise pin several GB on a crowded GPU.
    """
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass


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
    "repair": (
        "The following C++ program contains one or more bugs. "
        "Fix every bug and return the complete corrected source."
    ),
    "optimize": (
        "The following C++ program is correct but slow. Produce a strictly faster "
        "version that preserves identical observable behaviour on every test case."
    ),
}


_OPTIMIZE_RULES_FOOTER = (
    "Optimization Rules:\n"
    "- Encapsulate the optimized code within a C++ code block "
    "(i.e., ```cpp\\n[Your Code Here]\\n```).\n"
    "- Preserve identical stdout for EVERY test case (not only the one shown).\n"
    "- Do NOT change the I/O format. cin/cout/scanf/printf calls must produce "
    "the same bytes in the same order.\n"
    "- Focus solely on performance optimization; correctness is non-negotiable.\n"
    "- Do not include test driver code, comments explaining your changes, or "
    "any preamble outside the fenced block."
)

_REPAIR_RULES_FOOTER = (
    "Rules:\n"
    "- Encapsulate the fixed code within a C++ code block "
    "(i.e., ```cpp\\n[Your Code Here]\\n```).\n"
    "- Return the complete corrected source — not just a diff.\n"
    "- Do not include explanation outside the fenced block."
)


def _build_messages(buggy_code: str, feedback: str = None,
                    task_type: str = "repair",
                    problem_statement: str = None,
                    test_case_block: str = None,
                    tag_advice: str = None,
                    complexity_hint: str = None,
                    reasoning_hint: str = None) -> list:
    """
    Build the chat-template messages following EffiLearner's section layout
    (Task Description → Test Case → Original Code → Overhead Analysis →
    Reasoning Plan → Optimization Hints (tag-conditional) → Rules),
    generalised to either bug-repair or optimisation prompts.
    """
    sys_prompt = SYSTEM_PROMPTS.get(task_type, SYSTEM_PROMPTS["repair"])
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
    if reasoning_hint:
        parts.append(reasoning_hint.strip())
    if tag_advice:
        parts.append(tag_advice.strip())
    parts.append(_OPTIMIZE_RULES_FOOTER if task_type == "optimize"
                 else _REPAIR_RULES_FOOTER)

    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user",   "content": "\n\n".join(parts)},
    ]


def _extract_code(text: str) -> str:
    for pattern in [r"```cpp\s*(.*?)```", r"```c\s*(.*?)```", r"```\s*(.*?)```"]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return m.group(1).strip()
    return text.strip()


def repair(buggy_code: str, feedback: str = None,
           mode: str = "static", model_name: str = DEFAULT_MODEL,
           k: int = 1, temperature: float = 0.6, top_p: float = 0.95,
           seed: int = 0, task_type: str = "repair",
           problem_statement: str = None,
           test_case_block: str = None,
           tag_advice: str = None,
           complexity_hint: str = None,
           reasoning_hint: str = None) -> dict:
    """
    Repair buggy C++ code with a local model.

    k=1  -> greedy decoding, single candidate (deterministic).
    k>1  -> sampled decoding via num_return_sequences=k, returns k candidates.

    Returns a dict with `candidates` (list) plus `fixed_code` (= candidates[0])
    for backward compatibility.
    """
    load_model(model_name)

    import torch
    messages = _build_messages(buggy_code, feedback, task_type=task_type,
                               problem_statement=problem_statement,
                               test_case_block=test_case_block,
                               tag_advice=tag_advice,
                               complexity_hint=complexity_hint,
                               reasoning_hint=reasoning_hint)

    text = _tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = _tokenizer([text], return_tensors="pt").to(_model.device)
    prompt_tokens = inputs["input_ids"].shape[1]

    if k > 1:
        # Reproducibility across runs while still sampling diversity.
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        gen_kwargs = dict(
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            num_return_sequences=k,
        )
    else:
        gen_kwargs = dict(
            do_sample=False,
            temperature=None,
            top_p=None,
            top_k=None,
        )

    t0 = time.time()
    with torch.no_grad():
        output_ids = _model.generate(
            **inputs,
            max_new_tokens=1024,
            pad_token_id=_tokenizer.eos_token_id,
            **gen_kwargs,
        )
    elapsed = time.time() - t0

    # Decode each candidate (one row per returned sequence)
    candidates = []
    for row in output_ids:
        new_ids = row[prompt_tokens:]
        raw = _tokenizer.decode(new_ids, skip_special_tokens=True)
        candidates.append({
            "fixed_code": _extract_code(raw),
            "raw_response": raw,
            "completion_tokens": int(len(new_ids)),
        })

    return {
        "mode": mode,
        "model": model_name,
        "k": k,
        "temperature": temperature if k > 1 else 0.0,
        "fixed_code": candidates[0]["fixed_code"],          # back-compat
        "raw_response": candidates[0]["raw_response"],      # back-compat
        "completion_tokens": candidates[0]["completion_tokens"],
        "candidates": candidates,
        "prompt_tokens": prompt_tokens,
        "prompt_messages": messages,                        # for offline inspection
        "elapsed_s": round(elapsed, 2),
    }


def quick_inference(prompt: str, model_name: str = DEFAULT_MODEL,
                    max_new_tokens: int = 16) -> str:
    """
    Minimal one-shot inference for classification-style tasks. Loads the
    model on first call (same lazy mechanism as repair()), then runs a
    greedy generation with a short max_new_tokens budget.
    """
    load_model(model_name)
    import torch
    text = _tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        tokenize=False, add_generation_prompt=True,
    )
    inputs = _tokenizer([text], return_tensors="pt").to(_model.device)
    prompt_len = inputs["input_ids"].shape[1]
    with torch.no_grad():
        output_ids = _model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=None, top_p=None, top_k=None,
            pad_token_id=_tokenizer.eos_token_id,
        )
    new_ids = output_ids[0][prompt_len:]
    return _tokenizer.decode(new_ids, skip_special_tokens=True)


def repair_static(buggy_code: str, model_name: str = DEFAULT_MODEL, **kw) -> dict:
    return repair(buggy_code, feedback=None, mode="static",
                  model_name=model_name, **kw)


def repair_dynamic(buggy_code: str, runtime_feedback: str,
                   model_name: str = DEFAULT_MODEL, **kw) -> dict:
    """Runtime output diff only — no gprof / perf."""
    return repair(buggy_code, feedback=runtime_feedback,
                  mode="dynamic", model_name=model_name, **kw)


def repair_profiling(buggy_code: str, profile_summary: str,
                     model_name: str = DEFAULT_MODEL, **kw) -> dict:
    """Runtime output diff + gprof + perf counters."""
    return repair(buggy_code, feedback=profile_summary,
                  mode="profiling", model_name=model_name, **kw)


# ── Quick self-test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    from data.bugs import SAMPLES
    from compiler import compile_and_run
    from profiler import profile, format_profile_for_llm, format_runtime_feedback

    model_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    sample = SAMPLES[0]  # off-by-one

    print(f"Self-test: {sample['id']}  model={model_name}")

    # Build feedback blocks
    rb = compile_and_run(sample["buggy_code"], name="selftest_buggy",
                         expected_output=sample["expected_output"])
    runtime_fb = format_runtime_feedback(
        rb.get("compile_error", ""),
        actual_output=rb.get("stdout", ""),
        expected_output=sample["expected_output"],
    )
    raw_profile = profile(rb["binary_path"]) if rb["compiled"] else {}
    prof_summary = format_profile_for_llm(
        raw_profile, rb.get("compile_error", ""),
        actual_output=rb.get("stdout", ""),
        expected_output=sample["expected_output"],
    )

    # Static repair
    print("\n--- Static mode ---")
    sr = repair_static(sample["buggy_code"], model_name=model_name)
    sr_run = compile_and_run(sr["fixed_code"], name="selftest_static",
                              expected_output=sample["expected_output"])
    print(f"compiled={sr_run['compiled']}  passed={sr_run['passed']}  "
          f"tokens={sr['prompt_tokens']}+{sr['completion_tokens']}  "
          f"time={sr['elapsed_s']}s")

    # Dynamic repair (runtime output only)
    print("\n--- Dynamic mode (runtime output only) ---")
    dr = repair_dynamic(sample["buggy_code"], runtime_fb, model_name=model_name)
    dr_run = compile_and_run(dr["fixed_code"], name="selftest_dynamic",
                              expected_output=sample["expected_output"])
    print(f"compiled={dr_run['compiled']}  passed={dr_run['passed']}  "
          f"tokens={dr['prompt_tokens']}+{dr['completion_tokens']}  "
          f"time={dr['elapsed_s']}s")

    # Profiling repair (runtime + gprof + perf)
    print("\n--- Profiling mode (runtime + gprof + perf) ---")
    pr = repair_profiling(sample["buggy_code"], prof_summary, model_name=model_name)
    pr_run = compile_and_run(pr["fixed_code"], name="selftest_profiling",
                              expected_output=sample["expected_output"])
    print(f"compiled={pr_run['compiled']}  passed={pr_run['passed']}  "
          f"tokens={pr['prompt_tokens']}+{pr['completion_tokens']}  "
          f"time={pr['elapsed_s']}s")
