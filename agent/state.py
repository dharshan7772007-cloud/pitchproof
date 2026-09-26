"""
agent/state.py
--------------
Shared pipeline state contract for Pitchproof.

Every LangGraph node receives and returns a PitchproofState dict.
Fields are populated incrementally as the pipeline progresses:

    BugReport → RepoAnalysis → RootCause → FixPlan → CodeFix → TestGen → VerificationReport

All node implementations MUST:
  - Read only the fields they depend on.
  - Write only the field(s) they own.
  - Never mutate input data; return a partial dict with updated keys.
"""

from __future__ import annotations

from typing import List, Optional
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Sub-structures (plain dicts kept simple for JSON serialisation)
# ---------------------------------------------------------------------------

class RepoAnalysis(TypedDict):
    """Output of the repo_analyzer node."""
    suspect_files: List[str]          # Relative paths most likely containing the bug
    relevant_snippets: List[str]      # Short code excerpts (file:line — code)
    language: str                     # Primary language detected ("python", "java", …)
    summary: str                      # 1–2 sentence description of what was found


class RootCause(TypedDict):
    """Output of the root_cause node."""
    explanation: str                  # Human-readable root cause description
    fault_location: str               # "path/to/file.py:line_number"
    confidence: float                 # 0.0–1.0


class FixPlan(TypedDict):
    """Output of the fix_planner node."""
    steps: List[str]                  # Ordered list of fix steps
    affected_files: List[str]         # Files that will be modified
    rationale: str                    # Why this fix addresses the root cause


class TestResults(TypedDict):
    """Output of the test runner (subprocess execution)."""
    passed: int
    failed: int
    errors: int
    output: str                       # Raw pytest stdout/stderr


class VerificationReport(TypedDict):
    """Final output of the verifier node — rendered in the UI."""
    bug_summary: str
    root_cause_summary: str
    fix_description: str
    diff: str                         # Unified diff string
    test_results: TestResults
    confidence_score: float           # Aggregate confidence (0.0–1.0)
    status: str                       # "success" | "partial" | "failed"


# ---------------------------------------------------------------------------
# Pipeline stages — used by frontend progress tracker and status endpoint
# ---------------------------------------------------------------------------

PIPELINE_STAGES = [
    "repo_analysis",
    "root_cause",
    "fix_plan",
    "code_fix",
    "test_generation",
    "verification",
]


# ---------------------------------------------------------------------------
# Master state — passed through every LangGraph node
# ---------------------------------------------------------------------------

class PitchproofState(TypedDict):
    # ── Inputs ──────────────────────────────────────────────────────────────
    bug_report: str                               # Raw bug/error report text
    repo_url: str                                 # GitHub (or local) repo URL

    # ── Node outputs (None until that stage completes) ────────────────────
    repo_analysis: Optional[RepoAnalysis]
    root_cause: Optional[RootCause]
    fix_plan: Optional[FixPlan]
    code_diff: Optional[str]                      # Unified diff of the applied fix
    generated_tests: Optional[str]                # Full pytest file content
    test_results: Optional[TestResults]
    verification_report: Optional[VerificationReport]

    # ── Pipeline metadata ────────────────────────────────────────────────
    current_stage: str                            # One of PIPELINE_STAGES
    errors: List[str]                             # Non-fatal warnings / error messages
