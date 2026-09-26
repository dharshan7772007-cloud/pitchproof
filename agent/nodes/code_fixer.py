"""
agent/nodes/code_fixer.py
--------------------------
Node 4 of 6 — Code Fixing.

TODO (Track C): Implement real code generation using the LLM.
  - Read state["fix_plan"] and the relevant snippets from state["repo_analysis"].
  - Prompt the LLM to generate the corrected code.
  - Produce a unified diff string and write it to state["code_diff"].

Owner: Team Member responsible for Track C (Fix + Test + Verifier).
"""

from __future__ import annotations

from agent.state import PitchproofState


def code_fixer(state: PitchproofState) -> dict:
    """
    Generate and apply the code fix; produce a unified diff.

    Reads:   state["fix_plan"], state["repo_analysis"]
    Writes:  state["code_diff"], state["current_stage"]
    """
    # ── Placeholder implementation ─────────────────────────────────────────
    # Replace the body below with a real LLM call + diff generation.
    # from agent.llm import get_llm_client
    # llm = get_llm_client()
    # fixed_code = llm.invoke(build_code_fix_prompt(state))
    # diff = generate_unified_diff(original, fixed_code)

    placeholder_diff = (
        "--- a/path/to/file.py\n"
        "+++ b/path/to/file.py\n"
        "@@ -40,7 +40,7 @@\n"
        "-    [PLACEHOLDER] original line\n"
        "+    [PLACEHOLDER] fixed line\n"
        " [PLACEHOLDER] Code fix not yet implemented.\n"
    )

    return {
        "code_diff": placeholder_diff,
        "current_stage": "test_generation",
    }
