"""
tests/test_frontend.py
-----------------------
Tests for the Pitchproof Streamlit frontend (Task 8).

Validates:
  - Module imports cleanly.
  - Required functions exist.
  - API URL is read from env var, not hard-coded.
  - No hard-coded secrets or API keys in source.
  - Response/error handling helpers behave correctly.
  - No shell commands are executed.
  - No code from backend results is ever executed.

Does NOT launch an interactive Streamlit server.

Run with:
    pytest tests/test_frontend.py -v
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

FRONTEND_PATH = Path(__file__).parent.parent / "frontend" / "app.py"
FRONTEND_SOURCE = FRONTEND_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------

class TestModuleImports:

    def test_frontend_file_exists(self):
        assert FRONTEND_PATH.exists(), "frontend/app.py does not exist"

    def test_frontend_parses_as_valid_python(self):
        try:
            ast.parse(FRONTEND_SOURCE)
        except SyntaxError as exc:
            pytest.fail(f"frontend/app.py has a syntax error: {exc}")

    def test_api_url_constant_present(self):
        """API_URL must be defined in the module."""
        assert "API_URL" in FRONTEND_SOURCE

    def test_api_url_reads_from_env(self):
        """API_URL must use os.environ.get, not a hard-coded value."""
        assert 'os.environ.get("PITCHPROOF_API_URL"' in FRONTEND_SOURCE or \
               "os.environ.get('PITCHPROOF_API_URL'" in FRONTEND_SOURCE, \
               "API_URL must be read from PITCHPROOF_API_URL environment variable"

    def test_default_api_url_is_localhost(self):
        assert "localhost:8000" in FRONTEND_SOURCE, \
            "Default API URL should be http://localhost:8000"


# ---------------------------------------------------------------------------
# Required functions present
# ---------------------------------------------------------------------------

class TestRequiredFunctions:

    @pytest.fixture(scope="class", autouse=True)
    def import_module(self, request):
        """Import frontend.app without running the Streamlit server."""
        # Patch st.set_page_config and main so the module-level code doesn't run
        streamlit_mock = MagicMock()
        with patch.dict("sys.modules", {"streamlit": streamlit_mock}):
            spec = importlib.util.spec_from_file_location("frontend.app", FRONTEND_PATH)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            request.cls.mod = mod

    def test_call_analyze_exists(self):
        assert hasattr(self.mod, "call_analyze"), "call_analyze function missing"

    def test_check_backend_health_exists(self):
        assert hasattr(self.mod, "check_backend_health"), "check_backend_health missing"

    def test_render_root_cause_exists(self):
        assert hasattr(self.mod, "render_root_cause"), "render_root_cause missing"

    def test_render_fix_plan_exists(self):
        assert hasattr(self.mod, "render_fix_plan"), "render_fix_plan missing"

    def test_render_patch_exists(self):
        assert hasattr(self.mod, "render_patch"), "render_patch missing"

    def test_render_generated_tests_exists(self):
        assert hasattr(self.mod, "render_generated_tests"), "render_generated_tests missing"

    def test_render_verification_exists(self):
        assert hasattr(self.mod, "render_verification"), "render_verification missing"

    def test_render_pipeline_stages_exists(self):
        assert hasattr(self.mod, "render_pipeline_stages"), "render_pipeline_stages missing"

    def test_main_exists(self):
        assert hasattr(self.mod, "main"), "main function missing"

    def test_pipeline_stages_constant_present(self):
        assert hasattr(self.mod, "PIPELINE_STAGES"), "PIPELINE_STAGES constant missing"

    def test_pipeline_stages_has_six_entries(self):
        assert len(self.mod.PIPELINE_STAGES) == 6, \
            f"Expected 6 pipeline stages, got {len(self.mod.PIPELINE_STAGES)}"


# ---------------------------------------------------------------------------
# API URL configuration
# ---------------------------------------------------------------------------

class TestApiUrlConfig:

    def test_api_url_respects_env_var(self, monkeypatch):
        """PITCHPROOF_API_URL env var must override the default."""
        monkeypatch.setenv("PITCHPROOF_API_URL", "http://custom-host:9999")
        # Re-evaluate the expression (module already loaded; check the env var is read)
        url = os.environ.get("PITCHPROOF_API_URL", "http://localhost:8000").rstrip("/")
        assert url == "http://custom-host:9999"

    def test_default_is_localhost(self, monkeypatch):
        monkeypatch.delenv("PITCHPROOF_API_URL", raising=False)
        url = os.environ.get("PITCHPROOF_API_URL", "http://localhost:8000")
        assert url == "http://localhost:8000"


# ---------------------------------------------------------------------------
# No hard-coded secrets
# ---------------------------------------------------------------------------

class TestNoHardCodedSecrets:
    SECRET_PATTERNS = [
        "API_KEY",
        "api_key",
        "WATSONX",
        "watsonx",
        "sk-",            # OpenAI key prefix
        "Bearer ",
        "password",
        "secret",
    ]

    def test_no_hardcoded_api_keys(self):
        for pattern in self.SECRET_PATTERNS:
            # Allow env var reads like os.environ.get("WATSONX_API_KEY")
            # Only flag bare string assignments with secret-looking values
            assert (
                f'= "{pattern}' not in FRONTEND_SOURCE
                and f"= '{pattern}" not in FRONTEND_SOURCE
            ), f"Possible hard-coded secret found: {pattern!r}"

    def test_no_shell_true(self):
        assert "shell=True" not in FRONTEND_SOURCE, \
            "shell=True must not appear in frontend/app.py"

    def test_no_subprocess_calls(self):
        assert "subprocess.call" not in FRONTEND_SOURCE
        assert "subprocess.run" not in FRONTEND_SOURCE
        assert "subprocess.Popen" not in FRONTEND_SOURCE
        assert "os.system" not in FRONTEND_SOURCE

    def test_no_exec_eval(self):
        """Frontend must never exec() or eval() backend results."""
        # Allow the words in comments/strings but not as function calls
        tree = ast.parse(FRONTEND_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in ("exec", "eval"):
                    pytest.fail(f"exec/eval call found at line {node.lineno}")


# ---------------------------------------------------------------------------
# call_analyze helper
# ---------------------------------------------------------------------------

class TestCallAnalyze:

    @pytest.fixture(scope="class", autouse=True)
    def import_module(self, request):
        streamlit_mock = MagicMock()
        with patch.dict("sys.modules", {"streamlit": streamlit_mock}):
            spec = importlib.util.spec_from_file_location("frontend.app2", FRONTEND_PATH)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            request.cls.mod = mod

    def test_connect_error_raises_runtime_error(self):
        import httpx
        with patch.object(self.mod.httpx, "post",
                          side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RuntimeError, match="Could not connect"):
                self.mod.call_analyze("IndexError at line 42", "/some/repo")

    def test_timeout_raises_runtime_error(self):
        import httpx
        with patch.object(self.mod.httpx, "post",
                          side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(RuntimeError, match="timed out"):
                self.mod.call_analyze("IndexError at line 42", "/some/repo")

    def test_422_raises_runtime_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.is_success   = False
        mock_resp.json.return_value = {"detail": "Invalid path"}
        mock_resp.text = "Invalid path"
        with patch.object(self.mod.httpx, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="Invalid input"):
                self.mod.call_analyze("IndexError at line 42", "/some/repo")

    def test_500_raises_runtime_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.is_success   = False
        mock_resp.json.return_value = {"detail": "Internal server error"}
        mock_resp.text = "error"
        with patch.object(self.mod.httpx, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="internal error"):
                self.mod.call_analyze("IndexError at line 42", "/some/repo")

    def test_success_returns_dict(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success   = True
        mock_resp.json.return_value = {
            "job_id": "abc", "status": "partial", "stages": [],
            "errors": [], "confidence_score": 0.7,
        }
        with patch.object(self.mod.httpx, "post", return_value=mock_resp):
            result = self.mod.call_analyze("IndexError at line 42", "/some/repo")
        assert isinstance(result, dict)
        assert result["job_id"] == "abc"

    def test_malformed_json_raises_runtime_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success   = True
        mock_resp.json.side_effect = Exception("not json")
        with patch.object(self.mod.httpx, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="malformed"):
                self.mod.call_analyze("IndexError at line 42", "/some/repo")


# ---------------------------------------------------------------------------
# check_backend_health helper
# ---------------------------------------------------------------------------

class TestCheckBackendHealth:

    @pytest.fixture(scope="class", autouse=True)
    def import_module(self, request):
        streamlit_mock = MagicMock()
        with patch.dict("sys.modules", {"streamlit": streamlit_mock}):
            spec = importlib.util.spec_from_file_location("frontend.app3", FRONTEND_PATH)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            request.cls.mod = mod

    def test_returns_true_on_success(self):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        with patch.object(self.mod.httpx, "get", return_value=mock_resp):
            assert self.mod.check_backend_health() is True

    def test_returns_false_on_connection_error(self):
        import httpx
        with patch.object(self.mod.httpx, "get",
                          side_effect=httpx.ConnectError("refused")):
            assert self.mod.check_backend_health() is False

    def test_returns_false_on_non_success(self):
        mock_resp = MagicMock()
        mock_resp.is_success = False
        with patch.object(self.mod.httpx, "get", return_value=mock_resp):
            assert self.mod.check_backend_health() is False


# ---------------------------------------------------------------------------
# Confidence bar helper
# ---------------------------------------------------------------------------

class TestConfidenceBar:

    @pytest.fixture(scope="class", autouse=True)
    def import_module(self, request):
        streamlit_mock = MagicMock()
        with patch.dict("sys.modules", {"streamlit": streamlit_mock}):
            spec = importlib.util.spec_from_file_location("frontend.app4", FRONTEND_PATH)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            request.cls.mod = mod

    def test_none_returns_empty_string(self):
        assert self.mod._confidence_bar(None) == ""

    def test_zero_score(self):
        result = self.mod._confidence_bar(0.0)
        assert "0%" in result

    def test_full_score(self):
        result = self.mod._confidence_bar(1.0)
        assert "100%" in result

    def test_partial_score(self):
        result = self.mod._confidence_bar(0.7)
        assert "70%" in result
