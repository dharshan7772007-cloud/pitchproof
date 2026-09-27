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


def _build_prompt(bug_report: str, repo_analysis: RepoAnalysis) -> str:
    """Build the structured root-cause prompt."""

    snippets_block = "\n\n".join(
        repo_analysis.get("relevant_snippets") or []
    )

    suspect_list = "\n".join(
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

IMPORTANT:
- Only identify a fault location that exists in the Suspect Files above.
- Do not invent filenames.
- Do not use files that are not present in the supplied repository evidence.

Respond EXACTLY in this format:

EXPLANATION:
<one or two paragraphs explaining the root cause>

FAULT_LOCATION:
<file_path:line_number>

CONFIDENCE:
<a number between 0.0 and 1.0>

RECOMMENDED_FIX_DIRECTION:
<one paragraph describing the general approach to fix the bug>
"""


_SECTION_RE = re.compile(
    r"(EXPLANATION|FAULT_LOCATION|CONFIDENCE|RECOMMENDED_FIX_DIRECTION)"
    r"\s*:\s*\n(.*?)(?=\n(?:EXPLANATION|FAULT_LOCATION|CONFIDENCE|RECOMMENDED_FIX_DIRECTION)"
    r"\s*:|$)",
    re.DOTALL | re.IGNORECASE,
)


def _parse_llm_response(
    response: str,
    bug_report: str,
    repo_analysis: RepoAnalysis,
) -> RootCause:
    """Parse structured LLM output and validate its fault location."""

    sections: dict[str, str] = {}

    for match in _SECTION_RE.finditer(response):
        key = match.group(1).upper()
        value = match.group(2).strip()
        sections[key] = value

    explanation = sections.get("EXPLANATION", "").strip()

    if not explanation:
        explanation = response.strip() or (
            "Root cause could not be determined from the available information. "
            f"Bug report: {bug_report[:200]}"
        )

    fault_location = sections.get("FAULT_LOCATION", "unknown:0").strip()

    # Repository analysis is authoritative for the fault file.
    # Never allow the LLM to invent a file outside the analyzed repository.
    suspect_files = repo_analysis.get("suspect_files") or []

    if suspect_files:
        claimed_file = fault_location.split(":", 1)[0].strip()
        normalized_claim = claimed_file.replace("\\", "/").lower()

        matched_file = None

        for path in suspect_files:
            normalized_path = str(path).replace("\\", "/").lower()

            if normalized_claim == normalized_path:
                matched_file = str(path)
                break

            if normalized_claim == normalized_path.rsplit("/", 1)[-1]:
                matched_file = str(path)
                break

        if matched_file is None:
            # The LLM hallucinated a file. Use repository evidence.
            fault_location = f"{suspect_files[0]}:0"
        else:
            # Keep the LLM's line number only when the file is valid.
            line_part = fault_location.split(":", 1)[1] if ":" in fault_location else "0"
            fault_location = f"{matched_file}:{line_part}"

    elif not fault_location or fault_location.lower() in {"unknown", "n/a", ""}:
        fault_location = "unknown:0"

    # Validate the LLM's claimed file against repository evidence.
    # This prevents hallucinated paths such as auth.py.
    suspect_files = repo_analysis.get("suspect_files") or []

    if suspect_files:
        claimed_file = fault_location.split(":", 1)[0].strip()
        claimed_file_normalized = claimed_file.replace("\\", "/").lower()

        normalized_files = [
            str(path).replace("\\", "/").lower()
            for path in suspect_files
        ]

        valid_files = set(normalized_files)

        claimed_basename = claimed_file_normalized.rsplit("/", 1)[-1]

        valid_basenames = {
            path.rsplit("/", 1)[-1]
            for path in normalized_files
        }

        if (
            claimed_file_normalized not in valid_files
            and claimed_basename not in valid_basenames
        ):
            fault_location = f"{suspect_files[0]}:0"

    confidence = 0.0
    raw_conf = sections.get("CONFIDENCE", "0").strip()

    try:
        confidence = float(raw_conf)
        confidence = max(0.0, min(1.0, confidence))
    except ValueError:
        confidence = 0.0

    return RootCause(
        explanation=explanation,
        fault_location=fault_location,
        confidence=confidence,
    )


def root_cause(state: PitchproofState) -> dict:
    """
    Determine the root cause of the bug using LLM reasoning.

    Reads:   state["bug_report"], state["repo_analysis"]
    Writes:  state["root_cause"], state["current_stage"]
    """

    bug_report: str = state.get("bug_report", "")
    repo_analysis: Optional[RepoAnalysis] = state.get("repo_analysis")

    if repo_analysis is None:
        repo_analysis = RepoAnalysis(
            suspect_files=[],
            relevant_snippets=[],
            language="unknown",
            summary="Repository analysis was not available.",
        )

    prompt = _build_prompt(bug_report, repo_analysis)

    llm = get_llm_client()

    response = llm.invoke(
        prompt,
        max_tokens=1024,
        temperature=0.2,
    )

    result = _parse_llm_response(
        response,
        bug_report,
        repo_analysis,
    )

    return {
        "root_cause": result,
        "current_stage": "fix_plan",
    }