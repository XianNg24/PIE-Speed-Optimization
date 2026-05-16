# Reserach Topic: Profile Guided Code Correction using LLM

## Research Objectives
1. Develop a "Profiler-Aware" Agent: Create a system that can parse low-level data using profiling tools (e.g. perf, gprof) and translate them into natural language prompts. 
2. Determine if providing dynamic execution feedback (runtime metrics) significantly outperforms static analysis (reading code only) for code correctness.
Domain Focus: Measure on C++ for both code correctness and execution speed.

## Research Methodology & Structure
1. LLM generates a candidate solution.
2. System wraps code with Google Benchmark and compiles with debug symbols.
3. Run code execution and profiling to identify “hotspots” and capture perf stat.
4. LLM to refactor code based on the feedback prompt.
5. Verify code correctness and execution speed.

## Dataset
Defects4C for C++ code correctness. Github URL: https://github.com/defects4c/defects4c

## Models (≤16 GB VRAM, open-source)

All models below are instruction-tuned and fit on a single 16 GB GPU.
fp16 = full precision; Q4 = 4-bit NF4 quantisation via bitsandbytes.

| # | Model | Size | Precision | VRAM est. | Strength |
|---|-------|------|-----------|-----------|----------|
| 1 | **Qwen2.5-Coder-7B-Instruct** ⭐ | 7B | fp16 | ~14 GB | Best 7B code model (2024); top HumanEval/LiveCodeBench scores |
| 2 | **DeepSeek-Coder-6.7B-Instruct** | 6.7B | fp16 | ~13 GB | Strong bug-repair; fill-in-middle training |
| 3 | **CodeLlama-13B-Instruct** | 13B | Q4 | ~7 GB | Meta code-focused; good reasoning |
| 4 | **Qwen2.5-Coder-14B-Instruct** | 14B | Q4 | ~9 GB | Higher quality than 7B; fits with quantisation |
| 5 | **Llama-3.1-8B-Instruct** | 8B | fp16 | ~16 GB | General-purpose baseline for comparison |

> **First experiment model:** Qwen2.5-Coder-7B-Instruct (fp16, HuggingFace: `Qwen/Qwen2.5-Coder-7B-Instruct`)

## Experiment Plan
1. Run static vs dynamic pipeline on 5 synthetic bug samples.
2. Primary metric: pass@1 (does the LLM-fixed code produce correct output?).
3. Secondary metric: token cost (prompt tokens static vs dynamic).
4. Expand to real Defects4C samples once synthetic baseline is established.

