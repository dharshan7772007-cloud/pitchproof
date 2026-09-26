"""
agent/nodes/fix_planner.py
---------------------------
Node 3 of 6 — Fix Planning.

Consumes root_cause and repo_analysis from PitchproofState, calls the LLM to
produce a structured step-by-step fix plan, and parses the response into a
FixPlan dict.

Design principles:
  - Minimal and targeted changes preferred.
  - Never modifies repository files.
  - Gracefully degrades when root_cause or repo_analysis is incomplete.
  - Works with StubLLMClient when no credentials are configured.

Reads:   state["root_cause"], state["repo_analysis"], state["bug_report"]
Writes:  state["fix_plan"], state["current_stage"]
"""

from __future__ import annotations

import re
from typing import List, Optional

from agent.llm import get_llm_client
from agent.state import FixPlan, PitchproofState, RepoAnalysis, RootCause


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(
    bug_report: str,
    root_cause: RootCause,
    repo_analysis: RepoAnalysis,
) -> str:
    """
    Build the fix-planning prompt from available context.

    Instructs the LLM to respond in a structured, parseable format.
    """
    suspect_list = "\n".join(
        f"  - {f}" for f in (repo_analysis.get("suspect_files") or [])
    ) or "  (none identified)"

    snippets_block = "\n\n".join(
        repo_analysis.get("relevant_snippets") or []
    ) or "(no snippets available)"

    return f"""You are an expert software engineer creating a targeted bug-fix plan.

## Bug Report
{bug_report}

## Root Cause Analysis
Explanation: {root_cause.get('explanation', 'unknown')}
Fault Location: {root_cause.get('fault_location', 'unknown')}
Confidence: {root_cause.get('confidence', 0.0):.2f}

## Repository Context
Language: {repo_analysis.get('language', 'unknown')}
Suspect Files:
{suspect_list}

## Relevant Code Snippets
{snippets_block}

## Task
Produce a concise, targeted fix plan. Prefer minimal changes.

Respond EXACTLY in this format (do not add extra sections):

STEPS:
1. <first step>
2. <second step>
3. <third step — add more if needed>

AFFECTED_FILES:
<file1.py>
<file2.py — add more if needed>

RATIONALE:
<one or two paragraphs explaining why these changes fix the root cause,
what risks exist, and what the expected behaviour will be after the fix>
"""


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

_STEPS_RE = re.compile(
    r"STEPS\s*:\s*\n(.*?)(?=\nAFFECTED_FILES\s*:|$)",
    re.DOTALL | re.IGNORECASE,
)
_FILES_RE = re.compile(
    r"AFFECTED_FILES\s*:\s*\n(.*?)(?=\nRATIONALE\s*:|$)",
    re.DOTALL | re.IGNORECASE,
)
_RATIONALE_RE = re.compile(
    r"RATIONALE\s*:\s*\n(.*)",
    re.DOTALL | re.IGNORECASE,
)


def _parse_fix_plan(response: str, fault_location: str) -> FixPlan:
    """
    Parse the structured LLM output into a FixPlan dict.

    Falls back to safe defaults when sections are missing or malformed.
    """
    # ── Steps ────────────────────────────────────────────────────────────
    steps: List[str] = []
    steps_match = _STEPS_RE.search(response)
    if steps_match:
        raw_steps = steps_match.group(1).strip()
        for line in raw_steps.splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip leading numbering like "1." or "1)"
            step = re.sub(r"^\d+[.)]\s*", "", line).strip()
            if step:
                steps.append(step)

    if not steps:
        # Minimal fallback from fault location
        steps = [
            f"Locate the fault at: {fault_location}",
            "Apply the minimal code change to resolve the root cause.",
            "Run existing tests to confirm no regressions.",
        ]

    # ── Affected files ────────────────────────────────────────────────────
    affected_files: List[str] = []
    files_match = _FILES_RE.search(response)
    if files_match:
        for line in files_match.group(1).strip().splitlines():
            f = line.strip().lstrip("-• ")
            if f and not f.startswith("#"):
                affected_files.append(f)

    if not affected_files and fault_location not in {"unknown:0", "unknown", ""}:
        # Best-effort: extract the file part from "path/file.py:42"
        file_part = fault_location.split(":")[0].strip()
        if file_part:
            affected_files = [file_part]

    if not affected_files:
        affected_files = ["(file to be determined)"]

    # ── Rationale ────────────────────────────────────────────────────────
    rationale = ""
    rationale_match = _RATIONALE_RE.search(response)
    if rationale_match:
        rationale = rationale_match.group(1).strip()

    if not rationale:
        rationale = (
            "Fix plan generated from root-cause analysis. "
            "Verify against the codebase before applying changes."
        )

    return FixPlan(
        steps=steps,
        affected_files=affected_files,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def fix_planner(state: PitchproofState) -> dict:
    """
    Produce a step-by-step plan for fixing the identified bug.

    Reads:   state["root_cause"], state["repo_analysis"], state["bug_report"]
    Writes:  state["fix_plan"], state["current_stage"]
    """
    bug_report:    str                     = state.get("bug_report", "")
    root_cause:    Optional[RootCause]    = state.get("root_cause")
    repo_analysis: Optional[RepoAnalysis] = state.get("repo_analysis")

    # ── Graceful fallback for missing upstream data ───────────────────────
    if root_cause is None:
        root_cause = RootCause(
            explanation="Root cause analysis was not available.",
            fault_location="unknown:0",
            confidence=0.0,
        )

    if repo_analysis is None:
        repo_analysis = RepoAnalysis(
            suspect_files=[],
            relevant_snippets=[],
            language="unknown",
            summary="Repository analysis was not available.",
        )

    # ── Call LLM ──────────────────────────────────────────────────────────
    prompt   = _build_prompt(bug_report, root_cause, repo_analysis)
    llm      = get_llm_client()
    response = llm.invoke(prompt, max_tokens=1024, temperature=0.2)

    # ── Parse response ────────────────────────────────────────────────────
    plan = _parse_fix_plan(response, root_cause.get("fault_location", "unknown:0"))

    return {
        "fix_plan":      plan,
        "current_stage": "code_fix",
    }
