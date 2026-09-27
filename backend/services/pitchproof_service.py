import os
import uuid
from pathlib import Path
from typing import Any, Dict

from agent.graph import build_graph
from backend.models.schemas import PipelineResponse, PipelineStatus, StageResult


def validate_repo_path(repo_path: str) -> Path:
    if not repo_path or not repo_path.strip():
        raise ValueError("Repository path must not be empty.")

    if "\x00" in repo_path:
        raise ValueError("Repository path contains invalid characters.")

    path = Path(repo_path.strip()).resolve()

    # Streamlit Cloud sends its own source path to the API.
    # The FastAPI service runs in a separate container, so map the bundled
    # demo repository to the copy included with this backend deployment.
    if str(path).replace("\\", "/").endswith("/tests/fixtures/sample_repo"):
        path = (Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample_repo").resolve()

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


def run_analysis(
    bug_report: str,
    repo_path: str,
) -> PipelineResponse:

    if not bug_report or not bug_report.strip():
        raise ValueError("bug_report must not be empty.")

    validated_path = validate_repo_path(repo_path)

    # Deterministic hosted demo mode: used only when explicitly enabled
    # on the deployment. No code is executed or modified.
    if os.environ.get("PITCHPROOF_DEMO_MODE", "").lower() == "true":
        job_id = str(uuid.uuid4())
        demo_diff = """--- a/utils.py
+++ b/utils.py
@@
 def get_items(items: list, index: int):
-    return items[index]
+    if index < 0 or index >= len(items):
+        raise IndexError("list index out of range")
+    return items[index]
"""
        demo_tests = """# [GENERATED ? NOT EXECUTED]
import pytest

def test_get_items_valid_index():
    assert get_items(["a", "b"], 1) == "b"

def test_get_items_out_of_range():
    with pytest.raises(IndexError):
        get_items([], 0)
"""
        verification = {
            "status": "success",
            "bug_summary": "get_items can raise IndexError when the requested index is outside the valid list range.",
            "root_cause_summary": "utils.py:get_items accesses items[index] without validating that index is within the list bounds.",
            "fix_description": "Add an explicit bounds check before indexing the list.",
            "diff": demo_diff,
            "test_results": {
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "output": "[NOT EXECUTED] Tests were generated but not run."
            },
            "confidence_score": 0.94,
        }
        demo_state = _build_initial_state(bug_report.strip(), str(validated_path))
        demo_state["repo_analysis"] = {
            "suspect_files": ["utils.py"],
            "relevant_snippets": [],
            "language": "python",
            "summary": "Bundled demo repository analysed. utils.py is the relevant source file."
        }
        demo_state["root_cause"] = {
            "explanation": verification["root_cause_summary"],
            "fault_location": "utils.py:get_items",
            "confidence": 0.94,
        }
        demo_state["fix_plan"] = {
            "steps": [
                "Validate the requested index before list access.",
                "Raise a descriptive IndexError for invalid indexes.",
                "Add regression tests for valid and invalid indexes."
            ],
            "affected_files": ["utils.py"],
            "rationale": "Minimal bounds validation prevents the reported IndexError scenario."
        }
        demo_state["code_diff"] = demo_diff
        demo_state["generated_tests"] = demo_tests
        demo_state["test_results"] = verification["test_results"]
        demo_state["verification_report"] = verification
        demo_state["current_stage"] = "verification"
        return _state_to_response(demo_state, job_id)

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
            f"Analysis error: {type(exc).__name__}: {exc}"
        ) from None

    return _state_to_response(result, job_id)