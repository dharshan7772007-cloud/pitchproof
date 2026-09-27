"""
tests/test_backend.py
----------------------
Tests for the Pitchproof FastAPI backend (Task 7).

Coverage:
  - Application creation and startup.
  - GET /health and GET /api/health liveness probes.
  - POST /api/analyze: input validation, path validation, mocked pipeline.
  - POST /api/verify: patch validation, test validation, path checks.
  - Error responses: invalid input, path traversal, agent failure.
  - Security: no tracebacks or secrets exposed in responses.
  - JSON serialisability of all response models.

Uses FastAPI TestClient (synchronous).
All agent/LLM calls are mocked — no real API credentials required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_REPO  = str(FIXTURES_DIR / "sample_repo")

VALID_ANALYZE_PAYLOAD = {
    "bug_report": "IndexError: list index out of range in utils.py at line 11",
    "repo_url":   SAMPLE_REPO,
    "branch":     "main",
}

VALID_VERIFY_PAYLOAD = {
    "bug_report": "IndexError: list index out of range in utils.py at line 11",
    "repo_path":  SAMPLE_REPO,
    "code_diff": (
        "--- a/utils.py\n+++ b/utils.py\n"
        "@@ -9,4 +9,6 @@\n"
        " def get_items(items, index):\n"
        "+    if index >= len(items):\n"
        "+        return None\n"
        "     return items[index]\n"
    ),
    "generated_tests": (
        "import pytest\n\n"
        "def test_get_items_empty():\n"
        "    assert True\n"
    ),
}

# Minimal PipelineResponse-compatible dict returned by the mock service
_MOCK_PIPELINE_RESPONSE_DICT = {
    "job_id":             "mock-job-123",
    "status":             "partial",
    "current_stage":      "verification",
    "stages":             [],
    "bug_summary":        "Mock bug summary.",
    "root_cause_summary": "Mock root cause.",
    "fix_description":    "Mock fix.",
    "code_diff":          "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new",
    "generated_tests":    "def test_x():\n    assert True\n",
    "test_results":       {"passed": 0, "failed": 0, "errors": 0, "output": "[NOT EXECUTED]"},
    "confidence_score":   0.7,
    "errors":             [],
}


@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the Pitchproof app."""
    from backend.main import create_app
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _make_mock_response():
    """Build a PipelineResponse from the mock dict."""
    from backend.models.schemas import PipelineResponse
    return PipelineResponse(**_MOCK_PIPELINE_RESPONSE_DICT)


# ===========================================================================
# Application creation
# ===========================================================================

class TestAppCreation:

    def test_app_creates_without_error(self):
        from backend.main import create_app
        app = create_app()
        assert app is not None

    def test_app_has_title(self):
        from backend.main import create_app
        app = create_app()
        assert "Pitchproof" in app.title

    def test_module_level_app_exists(self):
        from backend.main import app
        assert app is not None


# ===========================================================================
# GET /health  (root endpoint)
# ===========================================================================

class TestRootHealth:

    def test_status_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.json()["status"] == "ok"

    def test_returns_service_name(self, client):
        resp = client.get("/health")
        assert resp.json()["service"] == "pitchproof"

    def test_is_json(self, client):
        resp = client.get("/health")
        assert resp.headers["content-type"].startswith("application/json")


# ===========================================================================
# GET /api/health
# ===========================================================================

class TestApiHealth:

    def test_status_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.json()["status"] == "ok"

    def test_returns_service_name(self, client):
        resp = client.get("/api/health")
        assert resp.json()["service"] == "pitchproof"

    def test_independent_of_agent(self, client):
        """Health endpoint must not trigger any agent logic."""
        with patch("backend.services.pitchproof_service.run_analysis") as mock_run:
            resp = client.get("/api/health")
            mock_run.assert_not_called()
        assert resp.status_code == 200


# ===========================================================================
# POST /api/analyze — input validation
# ===========================================================================

class TestAnalyzeValidation:

    def test_missing_bug_report_rejected(self, client):
        resp = client.post("/api/analyze", json={"repo_url": SAMPLE_REPO})
        assert resp.status_code == 422

    def test_missing_repo_url_rejected(self, client):
        resp = client.post("/api/analyze", json={
            "bug_report": "IndexError: list index out of range"
        })
        assert resp.status_code == 422

    def test_short_bug_report_rejected(self, client):
        resp = client.post("/api/analyze", json={
            "bug_report": "short",
            "repo_url":   SAMPLE_REPO,
        })
        assert resp.status_code == 422

    def test_blank_bug_report_rejected(self, client):
        resp = client.post("/api/analyze", json={
            "bug_report": "    ",
            "repo_url":   SAMPLE_REPO,
        })
        assert resp.status_code == 422

    def test_blank_repo_url_rejected(self, client):
        resp = client.post("/api/analyze", json={
            "bug_report": "IndexError: list index out of range in utils.py",
            "repo_url":   "   ",
        })
        assert resp.status_code == 422

    def test_empty_body_rejected(self, client):
        resp = client.post("/api/analyze", json={})
        assert resp.status_code == 422


# ===========================================================================
# POST /api/analyze — path security
# ===========================================================================

class TestAnalyzePathSecurity:

    def test_nonexistent_path_rejected(self, client):
        payload = {**VALID_ANALYZE_PAYLOAD, "repo_url": "/absolutely/nonexistent/path/xyz"}
        resp = client.post("/api/analyze", json=payload)
        assert resp.status_code in (422, 500)

    def test_traversal_path_rejected(self, client):
        payload = {**VALID_ANALYZE_PAYLOAD, "repo_url": "../../etc/passwd"}
        resp = client.post("/api/analyze", json=payload)
        assert resp.status_code in (422, 500)

    def test_file_path_rejected(self, client):
        # repo_url pointing to a file instead of directory
        payload = {**VALID_ANALYZE_PAYLOAD, "repo_url": str(FIXTURES_DIR / "sample_repo" / "utils.py")}
        resp = client.post("/api/analyze", json=payload)
        assert resp.status_code in (422, 500)

    def test_no_traceback_in_error_response(self, client):
        payload = {**VALID_ANALYZE_PAYLOAD, "repo_url": "/no/such/path"}
        resp = client.post("/api/analyze", json=payload)
        body = resp.text
        assert "Traceback" not in body
        assert "traceback" not in body

    def test_no_secrets_in_error_response(self, client):
        payload = {**VALID_ANALYZE_PAYLOAD, "repo_url": "/no/such/path"}
        resp = client.post("/api/analyze", json=payload)
        body = resp.text
        assert "API_KEY" not in body
        assert "WATSONX" not in body


# ===========================================================================
# POST /api/analyze — mocked pipeline
# ===========================================================================

class TestAnalyzeMocked:

    def test_valid_request_returns_200(self, client):
        mock_resp = _make_mock_response()
        with patch("backend.api.routes.run_analysis", return_value=mock_resp):
            resp = client.post("/api/analyze", json=VALID_ANALYZE_PAYLOAD)
        assert resp.status_code == 200

    def test_response_is_json_serialisable(self, client):
        mock_resp = _make_mock_response()
        with patch("backend.api.routes.run_analysis", return_value=mock_resp):
            resp = client.post("/api/analyze", json=VALID_ANALYZE_PAYLOAD)
        # Will raise if not valid JSON
        data = resp.json()
        assert isinstance(data, dict)

    def test_response_has_job_id(self, client):
        mock_resp = _make_mock_response()
        with patch("backend.api.routes.run_analysis", return_value=mock_resp):
            resp = client.post("/api/analyze", json=VALID_ANALYZE_PAYLOAD)
        assert "job_id" in resp.json()

    def test_response_has_status(self, client):
        mock_resp = _make_mock_response()
        with patch("backend.api.routes.run_analysis", return_value=mock_resp):
            resp = client.post("/api/analyze", json=VALID_ANALYZE_PAYLOAD)
        assert "status" in resp.json()

    def test_agent_value_error_returns_422(self, client):
        with patch("backend.api.routes.run_analysis",
                   side_effect=ValueError("invalid path")):
            resp = client.post("/api/analyze", json=VALID_ANALYZE_PAYLOAD)
        assert resp.status_code == 422
        assert "Traceback" not in resp.text

    def test_agent_runtime_error_returns_500(self, client):
        with patch("backend.api.routes.run_analysis",
                   side_effect=RuntimeError("pipeline failed")):
            resp = client.post("/api/analyze", json=VALID_ANALYZE_PAYLOAD)
        assert resp.status_code == 500
        assert "Traceback" not in resp.text

    def test_unexpected_exception_returns_500(self, client):
        with patch("backend.api.routes.run_analysis",
                   side_effect=Exception("INTERNAL_AGENT_CRASH_XYZ")):
            resp = client.post("/api/analyze", json=VALID_ANALYZE_PAYLOAD)
        assert resp.status_code == 500
        # Must not expose the raw internal exception message to API clients
        assert "INTERNAL_AGENT_CRASH_XYZ" not in resp.json().get("detail", "")


# ===========================================================================
# POST /api/verify
# ===========================================================================

class TestVerifyEndpoint:

    def test_valid_request_returns_200(self, client):
        resp = client.post("/api/verify", json=VALID_VERIFY_PAYLOAD)
        assert resp.status_code == 200

    def test_response_has_required_fields(self, client):
        resp = client.post("/api/verify", json=VALID_VERIFY_PAYLOAD)
        data = resp.json()
        for field in ("status", "confidence_score", "issues", "warnings",
                      "patch_valid", "tests_present", "test_syntax_ok", "summary"):
            assert field in data, f"Missing field: {field}"

    def test_valid_diff_recognised(self, client):
        resp = client.post("/api/verify", json=VALID_VERIFY_PAYLOAD)
        assert resp.json()["patch_valid"] is True

    def test_tests_present_when_provided(self, client):
        resp = client.post("/api/verify", json=VALID_VERIFY_PAYLOAD)
        assert resp.json()["tests_present"] is True

    def test_test_syntax_ok_for_valid_source(self, client):
        resp = client.post("/api/verify", json=VALID_VERIFY_PAYLOAD)
        assert resp.json()["test_syntax_ok"] is True

    def test_empty_diff_produces_issues(self, client):
        payload = {**VALID_VERIFY_PAYLOAD, "code_diff": ""}
        resp = client.post("/api/verify", json=payload)
        data = resp.json()
        assert data["patch_valid"] is False

    def test_broken_test_syntax_flagged(self, client):
        payload = {**VALID_VERIFY_PAYLOAD, "generated_tests": "def bad(:\n    pass\n"}
        resp = client.post("/api/verify", json=payload)
        data = resp.json()
        assert data["test_syntax_ok"] is False
        assert data["issues"]

    def test_missing_bug_report_rejected(self, client):
        payload = {k: v for k, v in VALID_VERIFY_PAYLOAD.items() if k != "bug_report"}
        resp = client.post("/api/verify", json=payload)
        assert resp.status_code == 422

    def test_missing_repo_path_rejected(self, client):
        payload = {k: v for k, v in VALID_VERIFY_PAYLOAD.items() if k != "repo_path"}
        resp = client.post("/api/verify", json=payload)
        assert resp.status_code == 422

    def test_invalid_repo_path_rejected(self, client):
        payload = {**VALID_VERIFY_PAYLOAD, "repo_path": "/no/such/path"}
        resp = client.post("/api/verify", json=payload)
        assert resp.status_code == 422

    def test_traversal_repo_path_rejected(self, client):
        payload = {**VALID_VERIFY_PAYLOAD, "repo_path": "../../etc"}
        resp = client.post("/api/verify", json=payload)
        assert resp.status_code in (422, 500)

    def test_no_diff_no_tests_returns_warnings(self, client):
        payload = {
            "bug_report": "IndexError in utils.py at line 11",
            "repo_path":  SAMPLE_REPO,
        }
        resp = client.post("/api/verify", json=payload)
        assert resp.status_code == 200
        assert resp.json()["warnings"]

    def test_response_is_json_serialisable(self, client):
        resp = client.post("/api/verify", json=VALID_VERIFY_PAYLOAD)
        data = resp.json()
        assert isinstance(data, dict)

    def test_confidence_score_in_range(self, client):
        resp = client.post("/api/verify", json=VALID_VERIFY_PAYLOAD)
        conf = resp.json()["confidence_score"]
        assert 0.0 <= conf <= 1.0


# ===========================================================================
# Service layer — validate_repo_path
# ===========================================================================

class TestServiceValidateRepoPath:

    def test_valid_directory_accepted(self):
        from backend.services.pitchproof_service import validate_repo_path
        result = validate_repo_path(SAMPLE_REPO)
        assert result.is_dir()

    def test_empty_string_raises(self):
        from backend.services.pitchproof_service import validate_repo_path
        with pytest.raises(ValueError, match="empty"):
            validate_repo_path("")

    def test_nonexistent_path_raises(self):
        from backend.services.pitchproof_service import validate_repo_path
        with pytest.raises(ValueError):
            validate_repo_path("/absolutely/nonexistent/xyz")

    def test_file_path_raises(self):
        from backend.services.pitchproof_service import validate_repo_path
        with pytest.raises(ValueError):
            validate_repo_path(str(FIXTURES_DIR / "sample_repo" / "utils.py"))

    def test_traversal_raises(self):
        from backend.services.pitchproof_service import validate_repo_path
        # On Windows the path may not exist, so accept "traversal" or "does not exist"
        with pytest.raises(ValueError):
            validate_repo_path("../../etc/passwd")

    def test_null_byte_raises(self):
        from backend.services.pitchproof_service import validate_repo_path
        with pytest.raises(ValueError):
            validate_repo_path("/tmp/re\x00po")


# ===========================================================================
# Service layer — run_analysis (mocked graph)
# ===========================================================================

class TestRunAnalysis:

    def _mock_graph_result(self):
        return {
            "bug_report":    "IndexError in utils.py",
            "repo_url":      SAMPLE_REPO,
            "repo_analysis": {"suspect_files": ["utils.py"], "relevant_snippets": [],
                               "language": "python", "summary": "ok"},
            "root_cause":    {"explanation": "bounds", "fault_location": "utils.py:11",
                               "confidence": 0.8},
            "fix_plan":      {"steps": ["add guard"], "affected_files": ["utils.py"],
                               "rationale": "prevents error"},
            "code_diff":     "--- a/utils.py\n+++ b/utils.py\n@@ -1 +1 @@\n-x\n+y",
            "generated_tests": "def test_x():\n    assert True\n",
            "test_results":  {"passed": 0, "failed": 0, "errors": 0,
                              "output": "[NOT EXECUTED]"},
            "verification_report": {
                "bug_summary": "bug", "root_cause_summary": "rc",
                "fix_description": "fix", "diff": "--- a\n+++ b\n@@ @@\n",
                "test_results": {"passed": 0, "failed": 0, "errors": 0, "output": ""},
                "confidence_score": 0.7, "status": "partial",
            },
            "current_stage": "verification",
            "errors": [],
        }

    def test_returns_pipeline_response(self):
        from backend.services.pitchproof_service import run_analysis
        from backend.models.schemas import PipelineResponse
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = self._mock_graph_result()
        with patch("backend.services.pitchproof_service.build_graph",
                   return_value=mock_graph):
            result = run_analysis("IndexError in utils.py at line 11", SAMPLE_REPO)
        assert isinstance(result, PipelineResponse)

    def test_has_job_id(self):
        from backend.services.pitchproof_service import run_analysis
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = self._mock_graph_result()
        with patch("backend.services.pitchproof_service.build_graph",
                   return_value=mock_graph):
            result = run_analysis("IndexError in utils.py at line 11", SAMPLE_REPO)
        assert result.job_id

    def test_invalid_repo_path_raises_value_error(self):
        from backend.services.pitchproof_service import run_analysis
        with pytest.raises(ValueError):
            run_analysis("IndexError in utils.py at line 11", "/no/such/path")

    def test_graph_exception_raises_runtime_error(self):
        from backend.services.pitchproof_service import run_analysis
        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = RuntimeError("graph exploded")
        with patch("backend.services.pitchproof_service.build_graph",
                   return_value=mock_graph):
            with pytest.raises(RuntimeError, match="pipeline encountered an error"):
                run_analysis("IndexError in utils.py at line 11", SAMPLE_REPO)

    def test_graph_exception_message_safe(self):
        """RuntimeError raised by service must not contain the raw exception message."""
        from backend.services.pitchproof_service import run_analysis
        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = Exception("SECRET_API_KEY=abc123")
        with patch("backend.services.pitchproof_service.build_graph",
                   return_value=mock_graph):
            try:
                run_analysis("IndexError in utils.py at line 11", SAMPLE_REPO)
            except RuntimeError as exc:
                assert "SECRET_API_KEY" not in str(exc)


# ===========================================================================
# Regression: DEMO_MODE bypass removed (bug: stale auth.py diagnosis)
# ===========================================================================

class TestNoDemoModeBypass:
    """
    Regression tests verifying that the DEMO_MODE shortcut that returned
    hardcoded auth.py / missing-user-validation results has been removed.

    The actual pipeline (build_graph) must ALWAYS be called for every
    run_analysis() invocation, regardless of any environment variable.
    """

    def _mock_graph_result(self):
        return {
            "bug_report":    "IndexError in utils.py at line 11",
            "repo_url":      SAMPLE_REPO,
            "repo_analysis": {"suspect_files": ["utils.py"],
                               "relevant_snippets": [],
                               "language": "python", "summary": "ok"},
            "root_cause":    {"explanation": "no bounds check",
                               "fault_location": "utils.py:11",
                               "confidence": 0.8},
            "fix_plan":      {"steps": ["add guard"], "affected_files": ["utils.py"],
                               "rationale": "prevents IndexError"},
            "code_diff":     "--- a/utils.py\n+++ b/utils.py\n@@ -9 +9 @@\n-x\n+y",
            "generated_tests": "def test_get_items_empty():\n    assert True\n",
            "test_results":  {"passed": 0, "failed": 0, "errors": 0,
                              "output": "[NOT EXECUTED]"},
            "verification_report": {
                "bug_summary": "IndexError when list is empty.",
                "root_cause_summary": "No bounds check in get_items.",
                "fix_description": "Add guard before index access.",
                "diff": "--- a/utils.py\n+++ b/utils.py\n@@ @@\n",
                "test_results": {"passed": 0, "failed": 0, "errors": 0, "output": ""},
                "confidence_score": 0.7,
                "status": "partial",
            },
            "current_stage": "verification",
            "errors": [],
        }

    def test_demo_mode_env_var_does_not_exist_in_service(self):
        """DEMO_MODE module-level variable must not exist in the service."""
        import backend.services.pitchproof_service as svc
        assert not hasattr(svc, "DEMO_MODE"), (
            "DEMO_MODE variable must not exist in pitchproof_service — "
            "it bypasses the pipeline with hardcoded auth.py results."
        )

    def test_build_demo_response_does_not_exist(self):
        """_build_demo_response must not exist in the service."""
        import backend.services.pitchproof_service as svc
        assert not hasattr(svc, "_build_demo_response"), (
            "_build_demo_response returns hardcoded stale results and must be removed."
        )

    def test_graph_always_called_regardless_of_env(self, monkeypatch):
        """
        Even if PITCHPROOF_DEMO_MODE=true is set in the environment,
        run_analysis() must still call build_graph().
        """
        monkeypatch.setenv("PITCHPROOF_DEMO_MODE", "true")
        from backend.services.pitchproof_service import run_analysis
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = self._mock_graph_result()
        with patch("backend.services.pitchproof_service.build_graph",
                   return_value=mock_graph):
            run_analysis("IndexError in utils.py at line 11", SAMPLE_REPO)
        mock_graph.invoke.assert_called_once()

    def test_result_reflects_actual_bug_report(self, monkeypatch):
        """
        The response must reflect the supplied bug report, not a hardcoded one.
        No auth.py / authentication content should appear when the input
        describes an IndexError in utils.py.
        """
        monkeypatch.setenv("PITCHPROOF_DEMO_MODE", "true")
        from backend.services.pitchproof_service import run_analysis
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = self._mock_graph_result()
        with patch("backend.services.pitchproof_service.build_graph",
                   return_value=mock_graph):
            result = run_analysis(
                "IndexError in utils.py at line 11", SAMPLE_REPO
            )
        # Must reference utils.py, not the hardcoded auth.py
        assert result.code_diff is not None
        assert "auth.py" not in (result.code_diff or ""), (
            "Response must not contain hardcoded auth.py diff."
        )

    def test_result_uses_graph_root_cause(self, monkeypatch):
        """
        root_cause_summary must come from the graph result, not a hardcoded value.
        """
        monkeypatch.setenv("PITCHPROOF_DEMO_MODE", "true")
        from backend.services.pitchproof_service import run_analysis
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = self._mock_graph_result()
        with patch("backend.services.pitchproof_service.build_graph",
                   return_value=mock_graph):
            result = run_analysis(
                "IndexError in utils.py at line 11", SAMPLE_REPO
            )
        # Must not contain the hardcoded auth copy
        assert "missing user record" not in (result.root_cause_summary or "").lower()
        assert "authentication" not in (result.root_cause_summary or "").lower()

    def test_affected_file_not_invented(self, monkeypatch):
        """
        Affected file in the graph response (utils.py) must pass through;
        the hardcoded auth.py must not appear.
        """
        monkeypatch.setenv("PITCHPROOF_DEMO_MODE", "true")
        from backend.services.pitchproof_service import run_analysis
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = self._mock_graph_result()
        with patch("backend.services.pitchproof_service.build_graph",
                   return_value=mock_graph):
            result = run_analysis(
                "IndexError in utils.py at line 11", SAMPLE_REPO
            )
        # The fix_plan stage output must reference what the graph returned
        fix_stage = next(
            (s for s in result.stages if s.stage == "fix_plan"), None
        )
        if fix_stage and fix_stage.output:
            files = fix_stage.output.get("affected_files", [])
            assert "auth.py" not in files, (
                "Hardcoded auth.py must not appear as an affected file."
            )
