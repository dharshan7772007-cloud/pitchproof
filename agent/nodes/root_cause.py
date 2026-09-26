"""
agent/nodes/root_cause.py
--------------------------
Node 2 of 6 — Root Cause Analysis.

Reads repo_analysis from the previous stage, builds a structured LLM prompt,
and parses the response into a RootCause dict.

Works with StubLLMClient when no real credentials are configured — tests never
require external API calls.

Reads:   state["bug_report"], state["repo_analysis"]
Writes:  state["root_cause"], state["current_stage"]
"""

from __future__ import annotations

import re
from typing import Optional

from agent.llm import get_llm_client
from agent.state import PitchproofState, RepoAnalysis, RootCause


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(bug_report: str, repo_analysis: RepoAnalysis) -> str:
    """
    Assemble the root-cause analysis prompt sent to the LLM.

    The prompt asks for a structured response with clearly delimited fields
    so it can be parsed without relying on exact JSON formatting.
    """
    snippets_block = "\n\n".join(repo_analysis.get("relevant_snippets") or [])
    suspect_list   = "\n".join(
        f"  - {f}" for f in (repo_analysis.get("suspect_files") or [])
    ) or "  (none identified)"

    return f"""You are an expert software debugger performing root-cause analysis.

## Bug Report
{bug_report}

## Repository Information
- Primary language: {repo_analysis.get('language', 'unknown')}
- Repository summary: {repo_analysis.get('summary', '')}

## Suspect Files
{suspect_list}

## Relevant Code Snippets
{snippets_block or '(no snippets available)'}

## Task
Analyse the bug report and code evidence above. Provide a structured root-cause analysis.

Respond EXACTLY in this format (do not add extra sections):

EXPLANATION:
<one or two paragraphs explaining the root cause>

FAULT_LOCATION:
<file_path:line_number or best guess>

CONFIDENCE:
<a number between 0.0 and 1.0>

RECOMMENDED_FIX_DIRECTION:
<one paragraph describing the general approach to fix the bug>
"""


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(
    r"(EXPLANATION|FAULT_LOCATION|CONFIDENCE|RECOMMENDED_FIX_DIRECTION)"
    r"\s*:\s*\n(.*?)(?=\n(?:EXPLANATION|FAULT_LOCATION|CONFIDENCE|RECOMMENDED_FIX_DIRECTION)\s*:|$)",
    re.DOTALL | re.IGNORECASE,
)


def _parse_llm_response(response: str, bug_report: str) -> RootCause:
    """
    Parse the structured LLM output into a RootCause dict.

    Falls back to sensible defaults if a section is missing or malformed.
    """
    sections: dict[str, str] = {}
    for match in _SECTION_RE.finditer(response):
        key   = match.group(1).upper()
        value = match.group(2).strip()
        sections[key] = value

    # ── Explanation ──────────────────────────────────────────────────────
    explanation = sections.get("EXPLANATION", "").strip()
    if not explanation:
        # Fall back: use the entire response if parsing failed
        explanation = response.strip() or (
            "Root cause could not be determined from the available information. "
            f"Bug report: {bug_report[:200]}"
        )

    # ── Fault location ───────────────────────────────────────────────────
    fault_location = sections.get("FAULT_LOCATION", "unknown:0").strip()
    if not fault_location or fault_location.lower() in {"unknown", "n/a", ""}:
        fault_location = "unknown:0"

    # ── Confidence ───────────────────────────────────────────────────────
    confidence = 0.0
    raw_conf = sections.get("CONFIDENCE", "0").strip()
    try:
        confidence = float(raw_conf)
        confidence = max(0.0, min(1.0, confidence))   # clamp to [0, 1]
    except ValueError:
        confidence = 0.0

    return RootCause(
        explanation=explanation,
        fault_location=fault_location,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def root_cause(state: PitchproofState) -> dict:
    """
    Determine the root cause of the bug using LLM reasoning.

    Reads:   state["bug_report"], state["repo_analysis"]
    Writes:  state["root_cause"], state["current_stage"]
    """
    bug_report:    str                     = state.get("bug_report", "")
    repo_analysis: Optional[RepoAnalysis] = state.get("repo_analysis")

    # ── Guard: if repo_analysis is missing, create a minimal fallback ────
    if repo_analysis is None:
        repo_analysis = RepoAnalysis(
            suspect_files=[],
            relevant_snippets=[],
            language="unknown",
            summary="Repository analysis was not available.",
        )

    # ── Build prompt and call LLM ────────────────────────────────────────
    prompt   = _build_prompt(bug_report, repo_analysis)
    llm      = get_llm_client()
    response = llm.invoke(prompt, max_tokens=1024, temperature=0.2)

    # ── Parse structured response ────────────────────────────────────────
    result = _parse_llm_response(response, bug_report)

    return {
        "root_cause":    result,
        "current_stage": "fix_plan",
    }
