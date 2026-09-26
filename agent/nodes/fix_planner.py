"""
agent/nodes/fix_planner.py
---------------------------
Node 3 of 6 — Fix Planning.

TODO (Track C): Implement real fix planning using the LLM.
  - Read state["root_cause"] and state["repo_analysis"].
  - Build a prompt asking the LLM to produce a step-by-step fix plan.
  - Populate state["fix_plan"] with a FixPlan dict.

Owner: Team Member responsible for Track C (Fix + Test + Verifier).
"""

from __future__ import annotations

from agent.state import FixPlan, PitchproofState


def fix_planner(state: PitchproofState) -> dict:
    """
    Produce a step-by-step plan for fixing the identified bug.

    Reads:   state["root_cause"], state["repo_analysis"]
    Writes:  state["fix_plan"], state["current_stage"]
    """
    # ── Placeholder implementation ─────────────────────────────────────────
    # Replace the body below with a real LLM call.
    # from agent.llm import get_llm_client
    # llm = get_llm_client()
    # response = llm.invoke(build_fix_plan_prompt(state))

    fix_plan: FixPlan = {
        "steps": [
            "[PLACEHOLDER] Step 1: Identify the exact fault location.",
            "[PLACEHOLDER] Step 2: Apply the minimal code change.",
            "[PLACEHOLDER] Step 3: Verify no regressions introduced.",
        ],
        "affected_files": ["[PLACEHOLDER] path/to/file.py"],
        "rationale": (
            "[PLACEHOLDER] Fix planning not yet implemented. "
            "Real implementation will use the LLM to propose a targeted fix."
        ),
    }

    return {
        "fix_plan": fix_plan,
        "current_stage": "code_fix",
    }
