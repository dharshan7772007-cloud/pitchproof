"""
backend/api/routes.py
----------------------
FastAPI route definitions for the Pitchproof API.

Endpoints:
  GET  /api/health    — lightweight liveness check (no agent dependency)
  POST /api/analyze   — run the full Pitchproof pipeline on a bug report
  POST /api/verify    — verify a proposed fix (re-runs verifier stage only)

All routes:
  - Validate input via Pydantic models.
  - Delegate business logic to backend/services/pitchproof_service.py.
  - Return safe, structured JSON responses.
  - Never expose Python tracebacks, secrets, or internal paths.
  - Never execute user-provided code or shell commands.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from backend.models.schemas import (
    BugReportRequest,
    PipelineResponse,
    PipelineStatus,
)
from backend.services.pitchproof_service import run_analysis

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Additional request/response models specific to this router
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "pitchproof"
    version: str = "0.1.0"


class VerifyRequest(BaseModel):
    """
    Request to verify a proposed fix.

    Accepts the outputs of a previous analysis run to perform validation.
    """
    bug_report: str = Field(..., min_length=10, max_length=8000)
    repo_path:  str = Field(..., description="Local path to the repository.")
    code_diff:  Optional[str] = Field(
        default=None,
        description="Unified diff of the proposed change.",
    )
    generated_tests: Optional[str] = Field(
        default=None,
        description="Generated pytest source to verify.",
    )
    root_cause_explanation: Optional[str] = Field(
        default=None,
        description="Root-cause explanation from a previous analysis.",
    )

    @field_validator("bug_report")
    @classmethod
    def _bug_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("bug_report must not be blank.")
        return v.strip()

    @field_validator("repo_path")
    @classmethod
    def _path_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("repo_path must not be blank.")
        return v.strip()


class VerifyResponse(BaseModel):
    """Structured verification result."""
    status:           str
    confidence_score: float
    issues:           list[str]
    warnings:         list[str]
    patch_valid:      bool
    tests_present:    bool
    test_syntax_ok:   bool
    summary:          str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="API health check",
    tags=["health"],
)
async def api_health() -> HealthResponse:
    """Lightweight liveness probe — no agent or database calls."""
    return HealthResponse()


@router.post(
    "/analyze",
    response_model=PipelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Run the Pitchproof bug-analysis pipeline",
    tags=["analysis"],
)
async def analyze(request: BugReportRequest) -> PipelineResponse:
    """
    Accept a bug report and repository path, run the full 6-stage pipeline,
    and return the complete analysis results.

    The repository must be a **local directory path** accessible to the server.
    Remote GitHub URLs are not yet supported in the MVP.
    """
    try:
        response = run_analysis(
            bug_report=request.bug_report,
            repo_path=request.repo_url,    # repo_url field holds the local path
        )
        return response

    except ValueError as exc:
        # Invalid input — safe to surface the message
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except RuntimeError as exc:
        # Agent pipeline error — safe generic message already set by service
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    except Exception:
        # Unexpected error — never expose details
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Check server logs.",
        )


@router.post(
    "/verify",
    response_model=VerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify a proposed fix",
    tags=["analysis"],
)
async def verify(request: VerifyRequest) -> VerifyResponse:
    """
    Run deterministic verification checks on a proposed fix without executing
    the full pipeline.

    Validates:
      - Repository path safety.
      - Proposed patch structure (diff format).
      - Generated test syntax.
    """
    from backend.services.pitchproof_service import validate_repo_path
    from agent.tools.test_tools import (
        TestSuite,
        parse_test_cases_from_text,
        validate_proposed_patch_structure,
        validate_test_syntax,
        check_test_targets_exist,
    )

    # Validate repo path first
    try:
        validated_path = validate_repo_path(request.repo_path)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    issues:   list[str] = []
    warnings: list[str] = []

    # ── Patch validation ──────────────────────────────────────────────────
    patch_valid = False
    if request.code_diff:
        patch_result = validate_proposed_patch_structure(request.code_diff)
        patch_valid  = patch_result.valid and not patch_result.issues
        issues.extend(patch_result.issues)
        warnings.extend(patch_result.warnings)
    else:
        warnings.append("No proposed diff provided; patch validation skipped.")

    # ── Test syntax validation ────────────────────────────────────────────
    test_syntax_ok = False
    tests_present  = bool(request.generated_tests and request.generated_tests.strip())
    if tests_present:
        syntax_result  = validate_test_syntax(request.generated_tests or "")
        test_syntax_ok = syntax_result.valid
        issues.extend(syntax_result.issues)
        warnings.extend(syntax_result.warnings)

        # Check target file existence
        test_cases = parse_test_cases_from_text(request.generated_tests or "")
        if test_cases:
            suite  = TestSuite(cases=test_cases, raw_source=request.generated_tests or "")
            t_res  = check_test_targets_exist(suite, str(validated_path))
            warnings.extend(t_res.issues)
            warnings.extend(t_res.warnings)
    else:
        warnings.append("No generated tests provided; test validation skipped.")

    # ── Determine status ──────────────────────────────────────────────────
    if issues:
        result_status = "failed"
    elif warnings:
        result_status = "partial"
    else:
        result_status = "partial"   # "success" requires actual test execution

    confidence = 0.0
    if patch_valid:
        confidence += 0.5
    if test_syntax_ok:
        confidence += 0.3
    if not issues:
        confidence += 0.2

    summary = (
        f"Verification {'failed' if issues else 'completed'}. "
        f"Patch {'valid' if patch_valid else 'invalid'}. "
        f"Tests {'present and syntactically valid' if test_syntax_ok else 'absent or invalid'}. "
        f"Confidence: {confidence:.0%}."
    )

    return VerifyResponse(
        status=result_status,
        confidence_score=round(confidence, 2),
        issues=issues,
        warnings=warnings,
        patch_valid=patch_valid,
        tests_present=tests_present,
        test_syntax_ok=test_syntax_ok,
        summary=summary,
    )
