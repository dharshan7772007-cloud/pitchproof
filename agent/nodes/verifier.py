"""
agent/nodes/verifier.py
------------------------
Node 6 of 6 — Verification & Report Generation.

TODO (Track C): Implement real verification using the LLM.
  - Aggregate results from all previous nodes.
  - Compute an overall confidence score.
  - Use the LLM to write a human-readable bug and fix summary.
  - Populate state["verification_report"] with a VerificationReport dict.

Owner: Team Member responsible for Track C (Fix + Test + Verifier).
"""

from __future__ import annotations

from agent.state import PitchproofState, VerificationReport


def verifier(state: PitchproofState) -> dict:
    """
    Aggregate all pipeline results into a final verification report.

    Reads:   All previous node outputs
    Writes:  state["verification_report"], state["current_stage"]
    """
    # ── Placeholder implementation ─────────────────────────────────────────
    # Replace the body below with real LLM summarisation + confidence scoring.
    # from agent.llm import get_llm_client
    # llm = get_llm_client()
    # summary = llm.invoke(build_verifier_prompt(state))

    # Derive a placeholder confidence from available test results
    test_results = state.get("test_results")
    placeholder_confidence = 0.0
    if test_results:
        total = test_results["passed"] + test_results["failed"] + test_results["errors"]
        if total > 0:
            placeholder_confidence = test_results["passed"] / total

    report: VerificationReport = {
        "bug_summary": (
            "[PLACEHOLDER] Bug summary not yet implemented. "
            f"Input bug report: {state.get('bug_report', '')[:120]}"
        ),
        "root_cause_summary": (
            state.get("root_cause", {}).get("explanation", "[PLACEHOLDER]")  # type: ignore[union-attr]
        ),
        "fix_description": "[PLACEHOLDER] Fix description not yet implemented.",
        "diff": state.get("code_diff") or "[PLACEHOLDER] No diff available.",
        "test_results": test_results or {"passed": 0, "failed": 0, "errors": 0, "output": ""},
        "confidence_score": placeholder_confidence,
        "status": "partial",
    }

    return {
        "verification_report": report,
        "current_stage": "verification",   # Terminal stage — no further transitions
    }
