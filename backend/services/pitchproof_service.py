import os
import uuid
from pathlib import Path
from typing import Any, Dict

from agent.graph import build_graph
from backend.models.schemas import PipelineResponse, PipelineStatus, StageResult


DEMO_MODE = os.environ.get("PITCHPROOF_DEMO_MODE", "false").lower() == "true"


def validate_repo_path(repo_path: str) -> Path:
    if not repo_path or not repo_path.strip():
        raise ValueError("Repository path must not be empty.")

    if "\x00" in repo_path:
        raise ValueError("Repository path contains invalid characters.")

    path = Path(repo_path.strip()).resolve()

    if not path.exists():
        raise ValueError("Repository path does not exist.")

    if not path.is_dir():
        raise ValueError("Repository path is not a directory.")

    return path


def _build_initial_state(bug_report: str, repo_path: str) -> Dict[str, Any]:
    return {
        "bug_report": bug_report,
        "repo_url": repo_path,
        "repo_analysis": None,
        "root_cause": None,
        "fix_plan": None,
        "code_diff": None,
        "generated_tests": None,
        "test_results": None,
        "verification_report": None,
        "current_stage": "repo_analysis",
        "errors": [],
    }


def _state_to_response(state: Dict[str, Any], job_id: str) -> PipelineResponse:
    from agent.state import PIPELINE_STAGES

    errors = list(state.get("errors") or [])
    verification = state.get("verification_report")

    if verification:
        raw_status = verification.get("status", "partial")
        status = {
            "success": PipelineStatus.SUCCESS,
            "partial": PipelineStatus.PARTIAL,
            "failed": PipelineStatus.FAILED,
        }.get(raw_status, PipelineStatus.PARTIAL)
    elif errors:
        status = PipelineStatus.FAILED
    else:
        status = PipelineStatus.PARTIAL

    stage_data = {
        "repo_analysis": state.get("repo_analysis"),
        "root_cause": state.get("root_cause"),
        "fix_plan": state.get("fix_plan"),
        "code_fix": (
            {"diff": state.get("code_diff")}
            if state.get("code_diff")
            else None
        ),
        "test_generation": (
            {"tests_present": bool(state.get("generated_tests"))}
        ),
        "verification": verification,
    }

    stages = []

    for stage_name in PIPELINE_STAGES:
        output = stage_data.get(stage_name)

        stages.append(
            StageResult(
                stage=stage_name,
                status=(
                    PipelineStatus.SUCCESS
                    if output
                    else PipelineStatus.PENDING
                ),
                output=output if isinstance(output, dict) else None,
            )
        )

    return PipelineResponse(
        job_id=job_id,
        status=status,
        current_stage=state.get("current_stage"),
        stages=stages,
        bug_summary=(
            verification.get("bug_summary")
            if verification
            else None
        ),
        root_cause_summary=(
            verification.get("root_cause_summary")
            if verification
            else None
        ),
        fix_description=(
            verification.get("fix_description")
            if verification
            else None
        ),
        code_diff=state.get("code_diff"),
        generated_tests=state.get("generated_tests"),
        test_results=state.get("test_results"),
        confidence_score=(
            verification.get("confidence_score")
            if verification
            else None
        ),
        errors=errors,
    )


def _build_demo_response(
    bug_report: str,
    repo_path: str,
) -> PipelineResponse:

    job_id = str(uuid.uuid4())

    demo_diff = """--- a/auth.py
+++ b/auth.py
@@
-    user = db.find_user(username)
-    return verify_password(password, user.password_hash)
+    user = db.find_user(username)
+    if user is None:
+        return {"error": "Invalid credentials"}, 401
+    return verify_password(password, user.password_hash)
"""

    demo_tests = """def test_login_invalid_user_returns_401():
    # DEMO TEST - NOT EXECUTED
    assert True


def test_login_valid_credentials():
    # DEMO TEST - NOT EXECUTED
    assert True
"""

    state = _build_initial_state(
        bug_report.strip(),
        str(repo_path),
    )

    state.update(
        {
            "repo_analysis": {
                "summary": "Repository scanned successfully.",
                "files_scanned": 6,
                "languages": ["Python"],
            },
            "root_cause": {
                "summary": (
                    "The login flow does not safely handle "
                    "a missing user record before accessing "
                    "authentication data."
                ),
                "location": "auth.py",
                "confidence": 0.94,
            },
            "fix_plan": {
                "steps": [
                    "Validate that the user exists before accessing password data.",
                    "Return a safe authentication error for unknown users.",
                    "Add regression tests for valid and invalid login cases.",
                ],
                "affected_files": ["auth.py"],
            },
            "code_diff": demo_diff,
            "generated_tests": demo_tests,
            "test_results": {
                "status": "NOT EXECUTED",
                "tests_generated": 2,
            },
            "verification_report": {
                "status": "success",
                "bug_summary": (
                    "Login endpoint returns HTTP 500 "
                    "for an authentication request."
                ),
                "root_cause_summary": (
                    "Missing user validation can cause "
                    "the authentication flow to access "
                    "unavailable user data."
                ),
                "fix_description": (
                    "Add an explicit user-existence check "
                    "before password verification."
                ),
                "confidence_score": 0.94,
            },
            "current_stage": "verification",
        }
    )

    return _state_to_response(state, job_id)


def run_analysis(
    bug_report: str,
    repo_path: str,
) -> PipelineResponse:

    if not bug_report or not bug_report.strip():
        raise ValueError("bug_report must not be empty.")

    validated_path = validate_repo_path(repo_path)

    if DEMO_MODE:
        return _build_demo_response(
            bug_report,
            validated_path,
        )

    job_id = str(uuid.uuid4())

    initial_state = _build_initial_state(
        bug_report.strip(),
        str(validated_path),
    )

    try:
        graph = build_graph()
        result = graph.invoke(initial_state)

    except Exception as exc:
        print(
            "[pitchproof_service] ERROR:",
            type(exc).__name__,
            str(exc),
        )

        raise RuntimeError(
            "The analysis pipeline encountered an error. "
            "Check server logs for details."
        ) from None

    return _state_to_response(result, job_id)