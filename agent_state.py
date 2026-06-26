"""
AgentState — per-(sample, mode) trajectory used by the agentic loop.

Phase 1 scope (this PR): lightweight dataclass that holds the trajectory of
attempts so the Critic agent can see what was tried before, and so we can
serialise the trajectory to disk for offline inspection.

Phase 2 will expand this to be the full orchestrator state (signals,
budgets, memory hooks). See architecture.md §3 / §6.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional
import json
import os


@dataclass
class Attempt:
    """One pass through Planner → Coder → Verifier."""
    attempt_idx: int
    plan: Optional[str]
    candidate_code: str
    verdict: dict          # {passed, compiled, failure_mode, mean_ms, speedup, per_test}
    critic_note: Optional[str] = None


@dataclass
class AgentState:
    sample_id: str
    mode: str              # "static" | "dynamic" | "profiling"
    problem_tag: Optional[str] = None
    attempts: list = field(default_factory=list)

    def add_attempt(self, *, plan: Optional[str], candidate_code: str,
                    verdict: dict, critic_note: Optional[str] = None) -> Attempt:
        a = Attempt(
            attempt_idx=len(self.attempts),
            plan=plan,
            candidate_code=candidate_code,
            verdict=verdict,
            critic_note=critic_note,
        )
        self.attempts.append(a)
        return a

    def last_failed_attempt(self) -> Optional[Attempt]:
        """Most recent failed attempt (any failure_mode)."""
        for a in reversed(self.attempts):
            if not a.verdict.get("passed"):
                return a
        return None

    def serialise(self, out_path: str) -> None:
        """Persist trajectory as JSON for the per-sample artefact directory."""
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        payload = {
            "sample_id": self.sample_id,
            "mode": self.mode,
            "problem_tag": self.problem_tag,
            "attempts": [asdict(a) for a in self.attempts],
        }
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
