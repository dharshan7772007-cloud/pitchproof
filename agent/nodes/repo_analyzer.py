"""
agent/nodes/repo_analyzer.py
-----------------------------
Node 1 of 6 — Repository Analysis.

TODO (Track B): Implement real repository analysis using GitPython + AST tools.
  - Clone or open the target repo from state["repo_url"].
  - Walk the file tree and identify files relevant to the bug report.
  - Extract short code snippets around suspected fault locations.
  - Detect the primary language.
  - Populate state["repo_analysis"] with a RepoAnalysis dict.

Owner: Team Member responsible for Track B (Repo Analyzer + Root Cause).
"""

from __future__ import annotations

from agent.state import PitchproofState, RepoAnalysis


def repo_analyzer(state: PitchproofState) -> dict:
    """
    Analyse the repository and locate files/code relevant to the bug report.

    Reads:   state["bug_report"], state["repo_url"]
    Writes:  state["repo_analysis"], state["current_stage"]
    """
    # ── Placeholder implementation ─────────────────────────────────────────
    # Replace the body below with real GitPython + AST analysis.
    # The return dict shape must match RepoAnalysis (agent/state.py).

    repo_analysis: RepoAnalysis = {
        "suspect_files": ["[PLACEHOLDER] path/to/suspected_file.py"],
        "relevant_snippets": [
            "[PLACEHOLDER] path/to/suspected_file.py:42 — <code snippet here>"
        ],
        "language": "python",
        "summary": (
            "[PLACEHOLDER] Repository analysis not yet implemented. "
            "Real implementation will clone the repo and identify fault locations."
        ),
    }

    return {
        "repo_analysis": repo_analysis,
        "current_stage": "root_cause",
    }
