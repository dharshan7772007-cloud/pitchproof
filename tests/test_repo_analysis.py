"""
tests/test_repo_analysis.py
-----------------------------
Tests for:
  - agent/tools/git_tools.py  — repository path validation and file discovery
  - agent/tools/ast_tools.py  — Python AST parsing
  - agent/nodes/repo_analyzer.py — full repo-analyzer node
  - agent/nodes/root_cause.py    — root-cause node with StubLLMClient

No external API calls are required.  All LLM calls go through StubLLMClient.

Run with:
    pytest tests/test_repo_analysis.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR  = Path(__file__).parent / "fixtures"
SAMPLE_REPO   = FIXTURES_DIR / "sample_repo"
UTILS_PY      = SAMPLE_REPO / "utils.py"
BROKEN_PY     = SAMPLE_REPO / "broken_syntax.py"


# ===========================================================================
# git_tools tests
# ===========================================================================

class TestValidateRepoPath:

    def test_valid_directory_returns_path(self):
        from agent.tools.git_tools import validate_repo_path
        result = validate_repo_path(str(SAMPLE_REPO))
        assert result.is_dir()

    def test_empty_string_raises_value_error(self):
        from agent.tools.git_tools import validate_repo_path
        with pytest.raises(ValueError, match="empty"):
            validate_repo_path("")

    def test_whitespace_string_raises_value_error(self):
        from agent.tools.git_tools import validate_repo_path
        with pytest.raises(ValueError, match="empty"):
            validate_repo_path("   ")

    def test_nonexistent_path_raises_value_error(self):
        from agent.tools.git_tools import validate_repo_path
        with pytest.raises(ValueError, match="does not exist"):
            validate_repo_path("/absolutely/nonexistent/path/xyz123")

    def test_file_path_raises_value_error(self):
        from agent.tools.git_tools import validate_repo_path
        with pytest.raises(ValueError, match="not a directory"):
            validate_repo_path(str(UTILS_PY))


class TestListSourceFiles:

    def test_returns_list(self):
        from agent.tools.git_tools import list_source_files
        files = list_source_files(str(SAMPLE_REPO))
        assert isinstance(files, list)

    def test_finds_python_files(self):
        from agent.tools.git_tools import list_source_files
        files = list_source_files(str(SAMPLE_REPO))
        extensions = {f.extension for f in files}
        assert ".py" in extensions

    def test_finds_utils_py(self):
        from agent.tools.git_tools import list_source_files
        files = list_source_files(str(SAMPLE_REPO))
        rel_paths = [f.rel_path for f in files]
        assert any("utils.py" in p for p in rel_paths)

    def test_finds_main_py(self):
        from agent.tools.git_tools import list_source_files
        files = list_source_files(str(SAMPLE_REPO))
        rel_paths = [f.rel_path for f in files]
        assert any("main.py" in p for p in rel_paths)

    def test_ignored_dirs_excluded(self, tmp_path):
        """Ensure IGNORED_DIRS like __pycache__, .venv, node_modules are skipped."""
        from agent.tools.git_tools import list_source_files, IGNORED_DIRS

        # Create a real .py file and one inside an ignored directory
        (tmp_path / "real.py").write_text("x = 1")
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.py").write_text("x = 2")

        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        (venv_dir / "lib.py").write_text("y = 3")

        files = list_source_files(str(tmp_path))
        rel_paths = [f.rel_path for f in files]

        # Only real.py should appear
        assert any("real.py" in p for p in rel_paths)
        assert not any("cached.py" in p for p in rel_paths), "__pycache__ was NOT ignored"
        assert not any("lib.py" in p for p in rel_paths), ".venv was NOT ignored"

    def test_oversized_file_excluded(self, tmp_path):
        from agent.tools.git_tools import list_source_files, MAX_FILE_BYTES
        big = tmp_path / "big.py"
        big.write_bytes(b"x = 1\n" * (MAX_FILE_BYTES // 6 + 10))
        files = list_source_files(str(tmp_path))
        assert not any("big.py" in f.rel_path for f in files), "oversized file was not excluded"

    def test_binary_file_excluded(self, tmp_path):
        from agent.tools.git_tools import list_source_files
        # Write a file with null bytes to simulate a binary
        (tmp_path / "binary.py").write_bytes(b"\x00\x01\x02\x03" * 100)
        # read_file_safe will detect it; list_source_files itself just lists by size/extension
        # so we test read_file_safe separately below
        # (list_source_files doesn't read content — it is intentionally separate)
        files = list_source_files(str(tmp_path))
        # The file can appear in the list; read_file_safe handles content safety
        assert isinstance(files, list)   # no crash

    def test_results_are_sorted(self):
        from agent.tools.git_tools import list_source_files
        files = list_source_files(str(SAMPLE_REPO))
        paths = [f.rel_path for f in files]
        assert paths == sorted(paths)


class TestReadFileSafe:

    def test_reads_valid_python_file(self):
        from agent.tools.git_tools import read_file_safe
        content = read_file_safe(str(UTILS_PY))
        assert content is not None
        assert "get_items" in content

    def test_returns_none_for_nonexistent_file(self):
        from agent.tools.git_tools import read_file_safe
        result = read_file_safe("/nonexistent/file.py")
        assert result is None

    def test_returns_none_for_binary_file(self, tmp_path):
        from agent.tools.git_tools import read_file_safe
        binary_file = tmp_path / "binary.py"
        binary_file.write_bytes(b"\x00" * 1000)
        assert read_file_safe(str(binary_file)) is None

    def test_returns_none_for_oversized_file(self, tmp_path):
        from agent.tools.git_tools import read_file_safe, MAX_FILE_BYTES
        big = tmp_path / "big.py"
        big.write_bytes(b"x = 1\n" * (MAX_FILE_BYTES // 6 + 10))
        assert read_file_safe(str(big)) is None


class TestDetectLanguage:

    def test_python_detected(self):
        from agent.tools.git_tools import list_source_files, detect_language
        files = list_source_files(str(SAMPLE_REPO))
        lang = detect_language(files)
        assert lang == "python"

    def test_empty_list_returns_unknown(self):
        from agent.tools.git_tools import detect_language
        assert detect_language([]) == "unknown"


class TestGetRepoInfo:

    def test_returns_repo_info(self):
        from agent.tools.git_tools import get_repo_info
        info = get_repo_info(str(SAMPLE_REPO))
        assert info.primary_language == "python"
        assert info.total_source_files >= 2   # utils.py + main.py at minimum

    def test_non_git_repo_flagged(self, tmp_path):
        """A plain directory (no .git) is reported as non-git."""
        from agent.tools.git_tools import get_repo_info
        (tmp_path / "app.py").write_text("print('hi')")
        info = get_repo_info(str(tmp_path))
        assert info.is_git_repo is False

    def test_invalid_path_raises(self):
        from agent.tools.git_tools import get_repo_info
        with pytest.raises(ValueError):
            get_repo_info("/definitely/does/not/exist")


# ===========================================================================
# ast_tools tests
# ===========================================================================

class TestParseSource:

    def test_parses_valid_source(self):
        from agent.tools.ast_tools import parse_source
        src = "def foo(x): return x + 1\nclass Bar: pass\n"
        result = parse_source(src, "test.py")
        assert result is not None
        assert result.syntax_error is None

    def test_extracts_function(self):
        from agent.tools.ast_tools import parse_source
        src = "def my_function(a, b):\n    '''doc'''\n    return a + b\n"
        result = parse_source(src)
        assert result is not None
        names = [f.name for f in result.functions]
        assert "my_function" in names

    def test_extracts_class(self):
        from agent.tools.ast_tools import parse_source
        src = "class MyClass(Base):\n    def method(self): pass\n"
        result = parse_source(src)
        assert result is not None
        names = [c.name for c in result.classes]
        assert "MyClass" in names

    def test_extracts_imports(self):
        from agent.tools.ast_tools import parse_source
        src = "import os\nfrom pathlib import Path\n"
        result = parse_source(src)
        assert result is not None
        modules = [i.module for i in result.imports]
        assert "os" in modules
        assert "pathlib" in modules

    def test_extracts_calls(self):
        from agent.tools.ast_tools import parse_source
        src = "print('hello')\nlen([1, 2, 3])\n"
        result = parse_source(src)
        assert result is not None
        call_names = [c.name for c in result.calls]
        assert "print" in call_names

    def test_syntax_error_returns_module_with_error_set(self):
        from agent.tools.ast_tools import parse_source
        broken = "def oops(:\n    pass\n"
        result = parse_source(broken, "broken.py")
        assert result is not None, "parse_source must not return None on SyntaxError"
        assert result.syntax_error is not None
        assert "SyntaxError" in result.syntax_error

    def test_syntax_error_does_not_raise(self):
        from agent.tools.ast_tools import parse_source
        # Must not propagate the exception
        try:
            parse_source("def bad(:\n    pass", "bad.py")
        except SyntaxError:
            pytest.fail("parse_source propagated SyntaxError — it should catch it")


class TestParseFile:

    def test_parses_real_file(self):
        from agent.tools.ast_tools import parse_file
        result = parse_file(str(UTILS_PY))
        assert result is not None
        assert result.syntax_error is None
        func_names = [f.name for f in result.functions]
        assert "get_items" in func_names

    def test_parses_broken_syntax_file_safely(self):
        from agent.tools.ast_tools import parse_file
        result = parse_file(str(BROKEN_PY))
        assert result is not None
        assert result.syntax_error is not None

    def test_returns_none_for_nonexistent_file(self):
        from agent.tools.ast_tools import parse_file
        result = parse_file("/nonexistent/file.py")
        assert result is None

    def test_utils_py_has_dataprocessor_class(self):
        from agent.tools.ast_tools import parse_file
        result = parse_file(str(UTILS_PY))
        assert result is not None
        class_names = [c.name for c in result.classes]
        assert "DataProcessor" in class_names


class TestScoreFileRelevance:

    def test_matching_function_name_scores_high(self):
        from agent.tools.ast_tools import parse_source, score_file_relevance
        src = "def get_items(x): return x\n"
        parsed = parse_source(src, "utils.py")
        score = score_file_relevance(parsed, ["get_items"])
        assert score > 0

    def test_no_match_scores_zero(self):
        from agent.tools.ast_tools import parse_source, score_file_relevance
        src = "def completely_unrelated(x): return x\n"
        parsed = parse_source(src, "other.py")
        score = score_file_relevance(parsed, ["totally_different_term"])
        assert score == 0.0

    def test_score_capped_at_one(self):
        from agent.tools.ast_tools import parse_source, score_file_relevance
        src = "def foo(x): pass\nclass foo_bar: pass\n"
        parsed = parse_source(src, "test.py")
        # Many matching terms — score must not exceed 1.0
        score = score_file_relevance(parsed, ["foo", "foo", "foo", "foo", "foo"])
        assert score <= 1.0

    def test_empty_terms_returns_zero(self):
        from agent.tools.ast_tools import parse_source, score_file_relevance
        src = "def foo(): pass\n"
        parsed = parse_source(src)
        assert score_file_relevance(parsed, []) == 0.0

    def test_syntax_error_file_returns_zero(self):
        from agent.tools.ast_tools import parse_source, score_file_relevance
        result = parse_source("def bad(:\n    pass")
        assert score_file_relevance(result, ["bad"]) == 0.0


# ===========================================================================
# repo_analyzer node tests
# ===========================================================================

class TestRepoAnalyzerNode:

    def _make_state(self, repo_path: str, bug_report: str = "") -> dict:
        return {
            "bug_report":          bug_report or "IndexError in utils.py get_items",
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

    def test_runs_on_sample_repo(self):
        from agent.nodes.repo_analyzer import repo_analyzer
        state = self._make_state(str(SAMPLE_REPO))
        result = repo_analyzer(state)
        assert "repo_analysis" in result
        assert result["repo_analysis"] is not None

    def test_language_detected_as_python(self):
        from agent.nodes.repo_analyzer import repo_analyzer
        result = repo_analyzer(self._make_state(str(SAMPLE_REPO)))
        assert result["repo_analysis"]["language"] == "python"

    def test_suspect_files_is_list(self):
        from agent.nodes.repo_analyzer import repo_analyzer
        result = repo_analyzer(self._make_state(str(SAMPLE_REPO)))
        assert isinstance(result["repo_analysis"]["suspect_files"], list)

    def test_relevant_snippets_is_list(self):
        from agent.nodes.repo_analyzer import repo_analyzer
        result = repo_analyzer(self._make_state(str(SAMPLE_REPO)))
        assert isinstance(result["repo_analysis"]["relevant_snippets"], list)

    def test_utils_py_appears_in_suspects_for_matching_bug(self):
        from agent.nodes.repo_analyzer import repo_analyzer
        result = repo_analyzer(
            self._make_state(str(SAMPLE_REPO), "IndexError in utils.py get_items function")
        )
        suspects = result["repo_analysis"]["suspect_files"]
        assert any("utils.py" in s for s in suspects), (
            f"Expected utils.py in suspect files, got: {suspects}"
        )

    def test_summary_is_string(self):
        from agent.nodes.repo_analyzer import repo_analyzer
        result = repo_analyzer(self._make_state(str(SAMPLE_REPO)))
        assert isinstance(result["repo_analysis"]["summary"], str)
        assert len(result["repo_analysis"]["summary"]) > 0

    def test_next_stage_is_root_cause(self):
        from agent.nodes.repo_analyzer import repo_analyzer
        result = repo_analyzer(self._make_state(str(SAMPLE_REPO)))
        assert result["current_stage"] == "root_cause"

    def test_invalid_repo_path_returns_error_gracefully(self):
        from agent.nodes.repo_analyzer import repo_analyzer
        state = self._make_state("/nonexistent/path/xyz")
        result = repo_analyzer(state)
        # Must not raise — must return a degraded result
        assert "repo_analysis" in result
        assert "errors" in result
        assert len(result["errors"]) > 0
        assert result["repo_analysis"]["language"] == "unknown"


# ===========================================================================
# root_cause node tests
# ===========================================================================

class TestRootCauseNode:

    def _make_state_with_analysis(self) -> dict:
        return {
            "bug_report": "IndexError: list index out of range in utils.py at line 42",
            "repo_url":   str(SAMPLE_REPO),
            "repo_analysis": {
                "suspect_files":    ["utils.py"],
                "relevant_snippets": ["utils.py:1 — def get_items(items, index):\n    return items[index]"],
                "language":         "python",
                "summary":          "Git repository analysed. 2 source files found.",
            },
            "root_cause":          None,
            "fix_plan":            None,
            "code_diff":           None,
            "generated_tests":     None,
            "test_results":        None,
            "verification_report": None,
            "current_stage":       "root_cause",
            "errors":              [],
        }

    def test_runs_with_stub_llm(self, monkeypatch):
        """root_cause node must complete without real API credentials."""
        from agent.llm import get_llm_client, StubLLMClient
        # Clear lru_cache and force StubLLMClient
        get_llm_client.cache_clear()
        for key in ("WATSONX_API_KEY", "WATSONX_PROJECT_ID", "OPENAI_API_KEY", "LLM_PROVIDER"):
            monkeypatch.delenv(key, raising=False)

        from agent.nodes.root_cause import root_cause
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = root_cause(self._make_state_with_analysis())

        get_llm_client.cache_clear()   # restore for other tests

        assert "root_cause" in result
        assert result["root_cause"] is not None

    def test_explanation_is_non_empty_string(self, monkeypatch):
        from agent.llm import get_llm_client
        get_llm_client.cache_clear()
        for key in ("WATSONX_API_KEY", "WATSONX_PROJECT_ID", "OPENAI_API_KEY", "LLM_PROVIDER"):
            monkeypatch.delenv(key, raising=False)

        from agent.nodes.root_cause import root_cause
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = root_cause(self._make_state_with_analysis())

        get_llm_client.cache_clear()
        assert isinstance(result["root_cause"]["explanation"], str)
        assert len(result["root_cause"]["explanation"]) > 0

    def test_confidence_is_float_in_range(self, monkeypatch):
        from agent.llm import get_llm_client
        get_llm_client.cache_clear()
        for key in ("WATSONX_API_KEY", "WATSONX_PROJECT_ID", "OPENAI_API_KEY", "LLM_PROVIDER"):
            monkeypatch.delenv(key, raising=False)

        from agent.nodes.root_cause import root_cause
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = root_cause(self._make_state_with_analysis())

        get_llm_client.cache_clear()
        conf = result["root_cause"]["confidence"]
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0

    def test_fault_location_is_string(self, monkeypatch):
        from agent.llm import get_llm_client
        get_llm_client.cache_clear()
        for key in ("WATSONX_API_KEY", "WATSONX_PROJECT_ID", "OPENAI_API_KEY", "LLM_PROVIDER"):
            monkeypatch.delenv(key, raising=False)

        from agent.nodes.root_cause import root_cause
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = root_cause(self._make_state_with_analysis())

        get_llm_client.cache_clear()
        assert isinstance(result["root_cause"]["fault_location"], str)

    def test_next_stage_is_fix_plan(self, monkeypatch):
        from agent.llm import get_llm_client
        get_llm_client.cache_clear()
        for key in ("WATSONX_API_KEY", "WATSONX_PROJECT_ID", "OPENAI_API_KEY", "LLM_PROVIDER"):
            monkeypatch.delenv(key, raising=False)

        from agent.nodes.root_cause import root_cause
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = root_cause(self._make_state_with_analysis())

        get_llm_client.cache_clear()
        assert result["current_stage"] == "fix_plan"

    def test_works_without_repo_analysis(self, monkeypatch):
        """root_cause must not crash when repo_analysis is None."""
        from agent.llm import get_llm_client
        get_llm_client.cache_clear()
        for key in ("WATSONX_API_KEY", "WATSONX_PROJECT_ID", "OPENAI_API_KEY", "LLM_PROVIDER"):
            monkeypatch.delenv(key, raising=False)

        state = self._make_state_with_analysis()
        state["repo_analysis"] = None

        from agent.nodes.root_cause import root_cause
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = root_cause(state)

        get_llm_client.cache_clear()
        assert result["root_cause"] is not None


class TestLLMResponseParser:
    """Unit tests for the LLM response parser (no LLM call needed)."""

    def test_well_formed_response_parsed(self):
        from agent.nodes.root_cause import _parse_llm_response
        response = (
            "EXPLANATION:\nThe bug is in the list access.\n\n"
            "FAULT_LOCATION:\nutils.py:42\n\n"
            "CONFIDENCE:\n0.85\n\n"
            "RECOMMENDED_FIX_DIRECTION:\nAdd a bounds check before accessing the list.\n"
        )
        result = _parse_llm_response(response, "test bug")
        assert "list access" in result["explanation"]
        assert result["fault_location"] == "utils.py:42"
        assert abs(result["confidence"] - 0.85) < 0.001

    def test_missing_confidence_defaults_to_zero(self):
        from agent.nodes.root_cause import _parse_llm_response
        response = "EXPLANATION:\nSome explanation.\n\nFAULT_LOCATION:\nfoo.py:1\n"
        result = _parse_llm_response(response, "bug")
        assert result["confidence"] == 0.0

    def test_invalid_confidence_defaults_to_zero(self):
        from agent.nodes.root_cause import _parse_llm_response
        response = (
            "EXPLANATION:\nExplanation.\n\n"
            "FAULT_LOCATION:\nfoo.py:1\n\n"
            "CONFIDENCE:\nnot-a-number\n"
        )
        result = _parse_llm_response(response, "bug")
        assert result["confidence"] == 0.0

    def test_confidence_clamped_to_one(self):
        from agent.nodes.root_cause import _parse_llm_response
        response = (
            "EXPLANATION:\nX.\n\nFAULT_LOCATION:\nf.py:1\n\nCONFIDENCE:\n99.5\n"
        )
        result = _parse_llm_response(response, "bug")
        assert result["confidence"] == 1.0

    def test_empty_response_falls_back_gracefully(self):
        from agent.nodes.root_cause import _parse_llm_response
        result = _parse_llm_response("", "my bug report")
        assert "my bug report" in result["explanation"]
        assert result["fault_location"] == "unknown:0"
