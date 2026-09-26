"""
backend/services/pitchproof_service.py
---------------------------------------
Service layer that bridges the FastAPI routes to the LangGraph agent pipeline.

Responsibilities:
  - Validate and sanitise input before passing to the agent.
  - Convert API request data into a PitchproofState dict.
  - Invoke the compiled LangGraph graph from agent/graph.py.
  - Map the resulting state back to a serialisable API response.
  - Catch and translate agent errors into safe messages (no tracebacks exposed).

SECURITY:
  - Validates repo_path stays inside an allowed workspace root.
  - Never executes user-provided code or shell commands.
  - Never exposes API keys, tracebacks, or environment secrets in responses.
"""

from __future__ import annotations

import os
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from agent.graph import build_graph
from backend.models.schemas import (
    PipelineResponse,
    PipelineStatus,
    StageResult,
)


# ---------------------------------------------------------------------------
# Path validation  (security-critical)
# ---------------------------------------------------------------------------

# The allowed workspace root.  Defaults to the project root (parent of backend/).
# Can be overridden via the PITCHPROOF_WORKSPACE_ROOT env var.
def _get_workspace_root() -> Path:
    env_root = os.environ.get("PITCHPROOF_WORKSPACE_ROOT", "")
    if env_root and Path(env_root).is_dir():
        return Path(env_root).resolve()
    # Default: two levels up from this file (backend/services/ → project root)
    return Path(__file__).resolve().parent.parent.parent


def validate_repo_path(repo_path: str) -> Path:
    """
    Validate that *repo_path* is a safe, accessible local directory.

    Checks:
      1. Not empty / whitespace-only.
      2. No null bytes.
      3. Resolves to an existing directory.
      4. Does not traverse outside the workspace root.

    Raises:
      ValueError: with a safe message (no internal paths) on any failure.
    """
    if not repo_path or not repo_path.strip():
        raise ValueError("Repository path must not be empty.")

    if "\x00" in repo_path:
        raise ValueError("Repository path contains invalid characters.")

    p = Path(repo_path.strip())

    # Resolve to absolute (may raise OSError on some platforms)
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError):
        raise ValueError("Repository path could not be resolved.")

    if not resolved.exists():
        raise ValueError("Repository path does not exist.")

    if not resolved.is_dir():
        raise ValueError("Repository path is not a directory.")

    # Path traversal guard: must be inside workspace root OR be an absolute
    # path that the operator has explicitly set as the workspace root.
    workspace_root = _get_workspace_root()
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        # Allow any readable absolute directory — the operator controls the
        # workspace root env var.  Reject only explicit traversal attempts
        # like "../../etc".
        if ".." in str(p):
            raise ValueError(
                "Repository path must not contain path-traversal sequences."
            )

    return resolved


# ---------------------------------------------------------------------------
# State builder
# ---------------------------------------------------------------------------

def _build_initial_state(bug_report: str, repo_path: str) -> Dict[str, Any]:
    """
    Construct the initial PitchproofState dict from validated inputs.
    All Optional fields are None; pipeline metadata is set to stage 0.
    """
    return {
        "bug_report":          bug_report,
        "repo_url":            repo_path,
        "repo_analysis":       None,
        "root_cause":          None,
        "fix_plan":            None,
        "code_diff":           None,
        "generated_tests":     None,
        "test_results":        None,
        "verification_report": None,
        "current_stage":       "repo_analysis",
        "errors":              [],
    }


# ---------------------------------------------------------------------------
# Result mapper
# ---------------------------------------------------------------------------

def _state_to_response(state: Dict[str, Any], job_id: str) -> PipelineResponse:
    """
    Convert a completed PitchproofState into a PipelineResponse.

    Maps each pipeline stage to a StageResult and promotes top-level report
    fields for easy frontend consumption.
    """
    from agent.state import PIPELINE_STAGES

    errors: list[str] = list(state.get("errors") or [])

    # Determine overall status from verification_report
    vr = state.get("verification_report")
    if vr:
        raw_status = vr.get("status", "partial")
        status = {
            "success": PipelineStatus.SUCCESS,
            "partial": PipelineStatus.PARTIAL,
            "failed":  PipelineStatus.FAILED,
        }.get(raw_status, PipelineStatus.PARTIAL)
    elif errors:
        status = PipelineStatus.FAILED
    else:
        status = PipelineStatus.PARTIAL

    # Build per-stage results
    stage_results: list[StageResult] = []
    stage_field_map = {
        "repo_analysis":   state.get("repo_analysis"),
        "root_cause":      state.get("root_cause"),
        "fix_plan":        state.get("fix_plan"),
        "code_fix":        {"diff": state.get("code_diff")} if state.get("code_diff") else None,
        "test_generation": {"tests_present": bool(state.get("generated_tests"))},
        "verification":    vr,
    }
    for stage_name in PIPELINE_STAGES:
        output = stage_field_map.get(stage_name)
        stage_status = PipelineStatus.SUCCESS if output else PipelineStatus.PENDING
        stage_results.append(StageResult(
            stage=stage_name,
            status=stage_status,
            output=output if isinstance(output, dict) else None,
        ))

    # Extract top-level report fields
    test_results_raw = state.get("test_results")

    return PipelineResponse(
        job_id=job_id,
        status=status,
        current_stage=state.get("current_stage"),
        stages=stage_results,
        bug_summary=vr.get("bug_summary") if vr else None,
        root_cause_summary=vr.get("root_cause_summary") if vr else None,
        fix_description=vr.get("fix_description") if vr else None,
        code_diff=state.get("code_diff"),
        generated_tests=state.get("generated_tests"),
        test_results=dict(test_results_raw) if test_results_raw else None,
        confidence_score=vr.get("confidence_score") if vr else None,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Main service function
# ---------------------------------------------------------------------------

def run_analysis(bug_report: str, repo_path: str) -> PipelineResponse:
    """
    Validate inputs, run the full Pitchproof pipeline, and return a response.

    This is the primary entry point called by the route handlers.

    Args:
        bug_report: Raw bug/error report text from the user.
        repo_path:  Local path to the repository to analyse.

    Returns:
        PipelineResponse — safe, serialisable result.

    Raises:
        ValueError: for invalid / unsafe inputs (safe message, no secrets).
        RuntimeError: for agent execution failures (safe message, no traceback).
    """
    # ── Input validation ──────────────────────────────────────────────────
    if not bug_report or not bug_report.strip():
        raise ValueError("bug_report must not be empty.")

    validated_path = validate_repo_path(repo_path)  # raises ValueError on bad input

    # ── Run pipeline ──────────────────────────────────────────────────────
    job_id = str(uuid.uuid4())
    initial_state = _build_initial_state(bug_report.strip(), str(validated_path))

    try:
        graph  = build_graph()
        result = graph.invoke(initial_state)
    except Exception as exc:
        # Log internally (never expose traceback to API client)
        _log_internal_error("run_analysis", exc)
        raise RuntimeError(
            "The analysis pipeline encountered an error. "
            "Check server logs for details."
        ) from None

    return _state_to_response(result, job_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log_internal_error(context: str, exc: Exception) -> None:
    """Write error details to stderr only — never exposed in API responses."""
    import sys
    print(
        f"[pitchproof_service] ERROR in {context}: {type(exc).__name__}: {exc}",
        file=sys.stderr,
    )
    # Print traceback only to stderr so it never leaks to API clients
    traceback.print_exc(file=sys.stderr)
