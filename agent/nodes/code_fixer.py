"""
agent/nodes/code_fixer.py
--------------------------
Node 4 of 6 — Code Fixing (proposed / dry-run).

Consumes fix_plan and repo_analysis from PitchproofState, calls the LLM to
generate a proposed code change, validates it via patch_tools, and returns
the unified diff as state["code_diff"].

IMPORTANT — this node operates in DRY-RUN mode:
  - Proposed changes are NEVER automatically written to disk.
  - The "applied" field on every ProposedChange remains False.
  - An authorised future step can write changes after human review.

Works with StubLLMClient when no LLM credentials are configured.

Reads:   state["fix_plan"], state["repo_analysis"], state["root_cause"],
         state["bug_report"], state["repo_url"]
Writes:  state["code_diff"], state["current_stage"]
"""

from __future__ import annotations

import re
from typing import List, Optional

from agent.llm import get_llm_client
from agent.state import FixPlan, PitchproofState, RepoAnalysis, RootCause
from agent.tools.patch_tools import (
    PatchSet,
    generate_unified_diff,
    make_patch_set,
    preview_patch_set,
)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(
    bug_report: str,
    root_cause: RootCause,
    fix_plan: FixPlan,
    repo_analysis: RepoAnalysis,
) -> str:
    """
    Build the code-generation prompt.

    Asks the LLM to output ONLY the proposed corrected code for each affected
    file, clearly delimited so it can be parsed.
    """
    steps_block = "\n".join(
        f"  {i+1}. {s}" for i, s in enumerate(fix_plan.get("steps") or [])
    ) or "  (no steps provided)"

    snippets_block = "\n\n".join(
        repo_analysis.get("relevant_snippets") or []
    ) or "(no snippets available)"

    affected = ", ".join(fix_plan.get("affected_files") or []) or "unknown"

    return f"""You are an expert software engineer generating a minimal, targeted code fix.

## Bug Report
{bug_report}

## Root Cause
{root_cause.get('explanation', 'unknown')}
Fault Location: {root_cause.get('fault_location', 'unknown')}

## Fix Plan
Files to change: {affected}
Steps:
{steps_block}

## Existing Code Snippets
{snippets_block}

## Task
Generate ONLY the corrected code for each file that needs to change.
Make the MINIMAL change required — do not refactor unrelated code.

For each file, respond in this EXACT format:

FILE: <relative/path/to/file.py>
DESCRIPTION: <one sentence describing what changed and why>
CODE:
```python
<complete corrected file content>
```

Repeat the FILE / DESCRIPTION / CODE block for each file that needs changing.
"""


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

_FILE_BLOCK_RE = re.compile(
    r"FILE\s*:\s*(?P<path>[^\n]+)\n"
    r"DESCRIPTION\s*:\s*(?P<desc>[^\n]+)\n"
    r"CODE\s*:\s*\n```(?:python|py)?\n(?P<code>.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def _parse_code_response(response: str) -> List[dict]:
    """
    Extract file-change entries from the structured LLM response.

    Returns a list of dicts compatible with make_patch_set():
        [{"rel_path": ..., "proposed_code": ..., "description": ...}, ...]
    """
    entries: List[dict] = []
    for match in _FILE_BLOCK_RE.finditer(response):
        rel_path = match.group("path").strip()
        desc     = match.group("desc").strip()
        code     = match.group("code").rstrip()
        if rel_path and code:
            entries.append({
                "rel_path":      rel_path,
                "proposed_code": code,
                "description":   desc or "LLM-generated fix",
            })
    return entries


def _stub_patch_set(fix_plan: FixPlan, repo_root: str) -> PatchSet:
    """
    Produce a safe, clearly labelled stub PatchSet when the LLM returns
    no parseable changes (e.g. StubLLMClient or unstructured response).
    """
    raw: List[dict] = []
    for f in (fix_plan.get("affected_files") or []):
        # Skip obviously non-file placeholders
        if "(" in f or not f.strip():
            continue
        raw.append({
            "rel_path":      f,
            "proposed_code": (
                "# [PROPOSED — NOT APPLIED]\n"
                "# This is a stub proposed change generated when the LLM\n"
                "# did not produce parseable code output.\n"
                "# Replace with the actual corrected file content.\n"
            ),
            "description": "Stub proposed change (LLM output was not parseable).",
        })

    if not raw:
        # Absolute fallback — no real file path available
        return PatchSet(
            changes=[],
            validation_errors=[
                "LLM did not produce parseable code changes. "
                "Configure a real LLM provider to generate actual fixes."
            ],
        )

    return make_patch_set(repo_root, raw)


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def code_fixer(state: PitchproofState) -> dict:
    """
    Generate a proposed code fix and return it as a unified diff.

    This is a DRY-RUN node: no files are written to disk.

    Reads:   state["fix_plan"], state["repo_analysis"],
             state["root_cause"], state["bug_report"], state["repo_url"]
    Writes:  state["code_diff"], state["current_stage"]
    """
    bug_report:    str                     = state.get("bug_report", "")
    repo_url:      str                     = state.get("repo_url", "")
    fix_plan:      Optional[FixPlan]       = state.get("fix_plan")
    root_cause:    Optional[RootCause]    = state.get("root_cause")
    repo_analysis: Optional[RepoAnalysis] = state.get("repo_analysis")

    # ── Graceful fallback for missing upstream data ───────────────────────
    if fix_plan is None:
        fix_plan = FixPlan(
            steps=["Apply a targeted fix to the identified fault location."],
            affected_files=[],
            rationale="Fix plan was not available; using minimal fallback.",
        )

    if root_cause is None:
        root_cause = RootCause(
            explanation="Root cause not available.",
            fault_location="unknown:0",
            confidence=0.0,
        )

    if repo_analysis is None:
        repo_analysis = RepoAnalysis(
            suspect_files=[],
            relevant_snippets=[],
            language="unknown",
            summary="Repository analysis not available.",
        )

    # Use repo_url as the root for path validation; fall back to current dir
    import os
    repo_root = repo_url if (repo_url and os.path.isdir(repo_url)) else os.getcwd()

    # ── Call LLM ──────────────────────────────────────────────────────────
    prompt   = _build_prompt(bug_report, root_cause, fix_plan, repo_analysis)
    llm      = get_llm_client()
    response = llm.invoke(prompt, max_tokens=2048, temperature=0.1)

    # ── Parse response into PatchSet ──────────────────────────────────────
    raw_changes = _parse_code_response(response)

    if raw_changes:
        patch_set = make_patch_set(repo_root, raw_changes)
    else:
        patch_set = _stub_patch_set(fix_plan, repo_root)

    # ── Produce unified diff string for state["code_diff"] ────────────────
    # Always mark as proposed — never applied here
    if patch_set.changes:
        code_diff = patch_set.as_unified_diff()
        if not code_diff.strip():
            # If diff is empty (identical content), describe the intent
            code_diff = preview_patch_set(patch_set)
    elif patch_set.validation_errors:
        code_diff = (
            "# [PROPOSED — NOT APPLIED]\n"
            "# Patch validation errors:\n"
            + "\n".join(f"#   {e}" for e in patch_set.validation_errors)
        )
    else:
        code_diff = "# [PROPOSED — NOT APPLIED]\n# No code changes were generated."

    return {
        "code_diff":     code_diff,
        "current_stage": "test_generation",
    }
