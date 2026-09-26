"""
backend/models/schemas.py
--------------------------
Pydantic request/response models for the Pitchproof FastAPI backend.

These models define the HTTP contract between the frontend and backend.
All agent nodes communicate via PitchproofState (see agent/state.py);
these schemas handle only the HTTP boundary.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, HttpUrl, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PipelineStatus(str, Enum):
    """Lifecycle states for a pipeline job."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"    # Completed with non-fatal errors
    FAILED  = "failed"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class BugReportRequest(BaseModel):
    """
    Submitted by the user to kick off the Pitchproof pipeline.

    Example payload:
        {
            "bug_report": "IndexError: list index out of range in utils.py line 42",
            "repo_url": "https://github.com/org/repo",
            "branch": "main"
        }
    """

    bug_report: str = Field(
        ...,
        min_length=10,
        max_length=8000,
        description="The raw bug report or error message to analyse.",
        examples=["IndexError: list index out of range in utils.py line 42"],
    )

    repo_url: str = Field(
        ...,
        description="GitHub URL or local path of the repository to analyse.",
        examples=["https://github.com/org/repo"],
    )

    branch: str = Field(
        default="main",
        description="Git branch to analyse. Defaults to 'main'.",
    )

    @field_validator("bug_report")
    @classmethod
    def bug_report_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("bug_report must not be blank or whitespace only.")
        return v.strip()

    @field_validator("repo_url")
    @classmethod
    def repo_url_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("repo_url must not be blank.")
        return v.strip()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class StageResult(BaseModel):
    """
    Result snapshot for a single pipeline stage.
    Used inside PipelineResponse to expose per-stage data.
    """
    stage: str
    status: PipelineStatus
    output: Optional[Dict] = None   # Stage-specific output (free-form JSON)
    error: Optional[str]  = None


class PipelineResponse(BaseModel):
    """
    Full status + results response for a pipeline job.

    Returned by:
        GET /status/{job_id}
        GET /report/{job_id}

    The `stages` list is ordered to match PIPELINE_STAGES in agent/state.py.
    """

    job_id: str = Field(..., description="Unique identifier for this pipeline run.")
    status: PipelineStatus
    current_stage: Optional[str] = Field(
        default=None,
        description="The pipeline stage currently executing (None if done).",
    )
    stages: List[StageResult] = Field(
        default_factory=list,
        description="Ordered per-stage results.",
    )

    # ── Final report fields (populated only when status == SUCCESS or PARTIAL) ──
    bug_summary: Optional[str]            = None
    root_cause_summary: Optional[str]     = None
    fix_description: Optional[str]        = None
    code_diff: Optional[str]              = None
    generated_tests: Optional[str]        = None
    test_results: Optional[Dict]          = None
    confidence_score: Optional[float]     = Field(default=None, ge=0.0, le=1.0)

    errors: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings or error messages accumulated during the run.",
    )


class JobCreatedResponse(BaseModel):
    """
    Returned immediately after POST /analyze to confirm job creation.
    The client polls GET /status/{job_id} for progress.
    """
    job_id: str
    message: str = "Pipeline job created. Poll /status/{job_id} for progress."
