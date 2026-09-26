"""
agent/nodes/root_cause.py
--------------------------
Node 2 of 6 — Root Cause Analysis.

TODO (Track B): Implement real root-cause analysis using the LLM.
  - Read state["bug_report"] and state["repo_analysis"].
  - Build a prompt that includes the bug report and relevant code snippets.
  - Call the LLM to produce a structured root-cause explanation.
  - Populate state["root_cause"] with a RootCause dict.

Owner: Team Member responsible for Track B (Repo Analyzer + Root Cause).
"""

from __future__ import annotations

from agent.state import PitchproofState, RootCause


def root_cause(state: PitchproofState) -> dict:
    """
    Determine the root cause of the bug using LLM reasoning.

    Reads:   state["bug_report"], state["repo_analysis"]
    Writes:  state["root_cause"], state["current_stage"]
    """
    # ── Placeholder implementation ─────────────────────────────────────────
    # Replace the body below with a real LLM call.
    # from agent.llm import get_llm_client
    # llm = get_llm_client()
    # response = llm.invoke(build_root_cause_prompt(state))

    root_cause_result: RootCause = {
        "explanation": (
            "[PLACEHOLDER] Root cause analysis not yet implemented. "
            "Real implementation will use the LLM to explain why the bug occurs."
        ),
        "fault_location": "[PLACEHOLDER] path/to/file.py:0",
        "confidence": 0.0,
    }

    return {
        "root_cause": root_cause_result,
        "current_stage": "fix_plan",
    }
