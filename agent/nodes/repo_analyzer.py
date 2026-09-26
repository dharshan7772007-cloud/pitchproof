"""
agent/nodes/repo_analyzer.py
-----------------------------
Node 1 of 6 — Repository Analysis.

Reads state["repo_url"] as a local filesystem path (URL support is a future
enhancement — for the MVP the user provides a local clone path).

Reads:   state["bug_report"], state["repo_url"]
Writes:  state["repo_analysis"], state["current_stage"]
"""

from __future__ import annotations

import re
from typing import List

from agent.state import PitchproofState, RepoAnalysis
from agent.tools.git_tools import get_repo_info, read_file_safe
from agent.tools.ast_tools import parse_file, score_file_relevance

# Maximum number of suspect files to surface
_MAX_SUSPECT_FILES = 10
# Maximum snippet length per file (characters)
_MAX_SNIPPET_CHARS = 400


def _extract_search_terms(bug_report: str) -> List[str]:
    """
    Pull simple identifier-like terms from a free-text bug report.

    Extracts:
      - Words that look like Python identifiers (CamelCase, snake_case)
      - File names mentioned (e.g. utils.py → "utils")
      - Function names if present

    Returns a deduplicated list of lowercase terms (length >= 3).
    """
    # Match identifiers: letters, digits, underscores — at least 3 chars
    raw = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", bug_report)
    # Also grab bare stems from "something.py" mentions
    stems = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\.py", bug_report)
    seen: set[str] = set()
    terms: List[str] = []
    for t in raw + stems:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            terms.append(key)
    return terms


def _make_snippet(abs_path: str, rel_path: str) -> str:
    """
    Read up to _MAX_SNIPPET_CHARS characters from *abs_path* and return a
    labelled snippet string: "rel_path:1 — <first lines of content>"
    """
    content = read_file_safe(abs_path)
    if not content:
        return f"{rel_path}:? — <unreadable>"
    truncated = content[:_MAX_SNIPPET_CHARS]
    if len(content) > _MAX_SNIPPET_CHARS:
        truncated += "\n… (truncated)"
    # Prefix the first line number (always 1 for a file header snippet)
    return f"{rel_path}:1 — {truncated}"


def repo_analyzer(state: PitchproofState) -> dict:
    """
    Analyse the repository and locate files/code relevant to the bug report.

    Reads:   state["bug_report"], state["repo_url"]
    Writes:  state["repo_analysis"], state["current_stage"]
    """
    bug_report: str = state.get("bug_report", "")
    repo_path:  str = state.get("repo_url", "")

    # ── Validate and inspect the repository ──────────────────────────────
    try:
        repo_info = get_repo_info(repo_path)
    except (ValueError, PermissionError) as exc:
        # Propagate a graceful degraded result rather than crashing the graph
        analysis: RepoAnalysis = {
            "suspect_files": [],
            "relevant_snippets": [],
            "language": "unknown",
            "summary": f"Repository could not be accessed: {exc}",
        }
        return {
            "repo_analysis": analysis,
            "current_stage": "root_cause",
            "errors": list(state.get("errors") or []) + [str(exc)],
        }

    # ── Extract search terms from the bug report ─────────────────────────
    search_terms = _extract_search_terms(bug_report)

    # ── Score each Python file for relevance ─────────────────────────────
    scored: list[tuple[float, str, str]] = []   # (score, rel_path, abs_path)

    for repo_file in repo_info.files:
        if repo_file.extension != ".py":
            # Non-Python files get a lower base score but are still considered
            # if their filename contains a search term
            name_score = sum(
                0.2 for t in search_terms if t in repo_file.rel_path.lower()
            )
            if name_score > 0:
                scored.append((name_score, repo_file.rel_path, repo_file.abs_path))
            continue

        parsed = parse_file(repo_file.abs_path)
        if parsed is None:
            continue

        # Boost score for filename match
        name_score = sum(
            0.2 for t in search_terms if t in repo_file.rel_path.lower()
        )
        ast_score = score_file_relevance(parsed, search_terms) if parsed else 0.0
        total = min(ast_score + name_score, 1.0)

        if total > 0:
            scored.append((total, repo_file.rel_path, repo_file.abs_path))

    # Sort descending by score, take top N
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:_MAX_SUSPECT_FILES]

    suspect_files = [rel for _, rel, _ in top]
    relevant_snippets = [
        _make_snippet(abs_path, rel)
        for _, rel, abs_path in top
    ]

    # ── Build summary ────────────────────────────────────────────────────
    git_label = "Git repository" if repo_info.is_git_repo else "Directory"
    summary = (
        f"{git_label} analysed. "
        f"Primary language: {repo_info.primary_language}. "
        f"{repo_info.total_source_files} source files found; "
        f"{len(suspect_files)} potentially relevant to the bug report."
    )

    analysis = RepoAnalysis(
        suspect_files=suspect_files,
        relevant_snippets=relevant_snippets,
        language=repo_info.primary_language,
        summary=summary,
    )

    return {
        "repo_analysis": analysis,
        "current_stage": "root_cause",
    }
