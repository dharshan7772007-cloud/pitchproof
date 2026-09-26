"""
tests/test_verifier.py
-----------------------
Tests for Task 6: Test Generator + Verifier + Test Tools.

Coverage:
  - agent/tools/test_tools.py   — syntax validation, TestSuite validation,
                                   LLM response parsing, patch validation,
                                   target path checks
  - agent/nodes/test_generator.py — test generation with StubLLMClient,
                                     NOT-EXECUTED sentinel, fallbacks
  - agent/nodes/verifier.py       — deterministic checks, confidence scoring,
                                     NOT-EXECUTED invariant, status logic

Security properties verified:
  - verifier never claims tests passed unless actually executed
  - path traversal in test targets rejected
  - no files written to disk
  - no code executed

No real API credentials required.

Run with:
    pytest tests/test_verifier.py -v
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_REPO  = FIXTURES_DIR / "sample_repo"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_llm_cache(monkeypatch):
    from agent.llm import get_llm_client
    get_llm_client.cache_clear()
    for key in ("WATSONX_API_KEY", "WATSONX_PROJECT_ID", "OPENAI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(key, raising=False)

def _restore_llm_cache():
    from agent.llm import get_llm_client
    get_llm_client.cache_clear()

def _full_state(repo_path: str = "") -> dict:
    return {
        "bug_report":   "IndexError: list index out of range in utils.py at line 11",
        "repo_url":     repo_path or str(SAMPLE_REPO),
        "repo_analysis": {
            "suspect_files":     ["utils.py"],
            "relevant_snippets": ["utils.py:1 — def get_items(items, index):\n    return items[index]"],
            "language":          "python",
            "summary":           "2 source files found.",
        },
        "root_cause": {
            "explanation":    "Access without bounds check causes IndexError.",
            "fault_location": "utils.py:11",
            "confidence":     0.85,
        },
        "fix_plan": {
            "steps":          ["Add a bounds check before indexing."],
            "affected_files": ["utils.py"],
            "rationale":      "Prevents IndexError on empty list.",
        },
        "code_diff": (
            "--- a/utils.py\n+++ b/utils.py\n"
            "@@ -9,7 +9,9 @@\n"
            "-def get_items(items, index):\n"
            "+def get_items(items, index):\n"
            "+    if index >= len(items):\n"
            "+        return None\n"
            "     return items[index]\n"
        ),
        "generated_tests":     None,
        "test_results":        None,
        "verification_report": None,
        "current_stage":       "test_generation",
        "errors":              [],
    }


# ===========================================================================
# test_tools — validate_test_syntax
# ===========================================================================

class TestValidateTestSyntax:

    def test_valid_python_passes(self):
        from agent.tools.test_tools import validate_test_syntax
        r = validate_test_syntax("def test_foo():\n    assert True\n")
        assert r.valid
        assert not r.issues

    def test_empty_source_fails(self):
        from agent.tools.test_tools import validate_test_syntax
        r = validate_test_syntax("")
        assert not r.valid
        assert r.issues

    def test_whitespace_only_fails(self):
        from agent.tools.test_tools import validate_test_syntax
        r = validate_test_syntax("   \n  ")
        assert not r.valid

    def test_syntax_error_detected(self):
        from agent.tools.test_tools import validate_test_syntax
        r = validate_test_syntax("def bad(:\n    pass\n")
        assert not r.valid
        assert any("SyntaxError" in i for i in r.issues)

    def test_syntax_error_does_not_raise(self):
        from agent.tools.test_tools import validate_test_syntax
        try:
            validate_test_syntax("def bad(:\n    pass")
        except SyntaxError:
            pytest.fail("validate_test_syntax must not propagate SyntaxError")


# ===========================================================================
# test_tools — validate_test_suite
# ===========================================================================

class TestValidateTestSuite:

    def _make_case(self, **kw):
        from agent.tools.test_tools import TestCase
        defaults = dict(
            objective="verify fix", target_file="utils.py",
            target_func="get_items", test_type="regression",
            input_data="get_items([], 0)", expected="None returned",
            rationale="Tests the guard clause",
        )
        defaults.update(kw)
        return TestCase(**defaults)

    def test_valid_suite_passes(self):
        from agent.tools.test_tools import TestSuite, validate_test_suite
        suite = TestSuite(
            cases=[self._make_case()],
            raw_source="def test_x():\n    assert True\n",
        )
        r = validate_test_suite(suite)
        assert r.valid

    def test_empty_suite_fails(self):
        from agent.tools.test_tools import TestSuite, validate_test_suite
        r = validate_test_suite(TestSuite())
        assert not r.valid

    def test_missing_objective_fails(self):
        from agent.tools.test_tools import TestSuite, validate_test_suite
        suite = TestSuite(cases=[self._make_case(objective="")])
        r = validate_test_suite(suite)
        assert not r.valid

    def test_missing_target_file_fails(self):
        from agent.tools.test_tools import TestSuite, validate_test_suite
        suite = TestSuite(cases=[self._make_case(target_file="")])
        r = validate_test_suite(suite)
        assert not r.valid

    def test_missing_expected_fails(self):
        from agent.tools.test_tools import TestSuite, validate_test_suite
        suite = TestSuite(cases=[self._make_case(expected="")])
        r = validate_test_suite(suite)
        assert not r.valid

    def test_broken_source_fails(self):
        from agent.tools.test_tools import TestSuite, validate_test_suite
        suite = TestSuite(
            cases=[self._make_case()],
            raw_source="def bad(:\n    pass\n",
        )
        r = validate_test_suite(suite)
        assert not r.valid

    def test_source_without_test_functions_warns(self):
        from agent.tools.test_tools import TestSuite, validate_test_suite
        suite = TestSuite(
            cases=[self._make_case()],
            raw_source="x = 1\n",   # valid python but no test_* functions
        )
        r = validate_test_suite(suite)
        assert r.warnings   # should warn about missing test_* functions


# ===========================================================================
# test_tools — parse_test_cases_from_text
# ===========================================================================

class TestParseTestCasesFromText:

    def test_single_well_formed_case(self):
        from agent.tools.test_tools import parse_test_cases_from_text
        text = (
            "TEST_CASE 1:\n"
            "OBJECTIVE: Verify bounds check\n"
            "TARGET_FILE: utils.py\n"
            "TARGET_FUNC: get_items\n"
            "TEST_TYPE: regression\n"
            "INPUT: get_items([], 0)\n"
            "EXPECTED: None returned\n"
            "RATIONALE: Tests the guard clause\n"
        )
        cases = parse_test_cases_from_text(text)
        assert len(cases) == 1
        assert cases[0].target_file == "utils.py"
        assert cases[0].target_func == "get_items"
        assert cases[0].test_type == "regression"

    def test_multiple_cases_parsed(self):
        from agent.tools.test_tools import parse_test_cases_from_text
        text = (
            "TEST_CASE 1:\n"
            "OBJECTIVE: Test A\nTARGET_FILE: a.py\nTARGET_FUNC: fa\n"
            "TEST_TYPE: unit\nINPUT: x\nEXPECTED: y\nRATIONALE: r\n\n"
            "TEST_CASE 2:\n"
            "OBJECTIVE: Test B\nTARGET_FILE: b.py\nTARGET_FUNC: fb\n"
            "TEST_TYPE: regression\nINPUT: a\nEXPECTED: b\nRATIONALE: s\n"
        )
        cases = parse_test_cases_from_text(text)
        assert len(cases) == 2

    def test_empty_text_returns_empty_list(self):
        from agent.tools.test_tools import parse_test_cases_from_text
        assert parse_test_cases_from_text("") == []

    def test_stub_response_returns_empty_list(self):
        from agent.tools.test_tools import parse_test_cases_from_text
        stub = "[STUB] LLM not configured. Set WATSONX_API_KEY..."
        assert parse_test_cases_from_text(stub) == []

    def test_malformed_text_returns_empty_list(self):
        from agent.tools.test_tools import parse_test_cases_from_text
        assert parse_test_cases_from_text("random text with no structure") == []


# ===========================================================================
# test_tools — validate_proposed_patch_structure
# ===========================================================================

class TestValidateProposedPatchStructure:

    def test_valid_diff_passes(self):
        from agent.tools.test_tools import validate_proposed_patch_structure
        diff = (
            "--- a/utils.py\n+++ b/utils.py\n"
            "@@ -1,3 +1,4 @@\n"
            " def foo():\n-    return 1\n+    return 2\n"
        )
        r = validate_proposed_patch_structure(diff)
        assert r.valid

    def test_empty_diff_fails(self):
        from agent.tools.test_tools import validate_proposed_patch_structure
        r = validate_proposed_patch_structure("")
        assert not r.valid

    def test_comment_only_fails(self):
        from agent.tools.test_tools import validate_proposed_patch_structure
        r = validate_proposed_patch_structure(
            "# [PROPOSED — NOT APPLIED]\n# stub\n"
        )
        assert not r.valid

    def test_no_hunk_header_warns(self):
        from agent.tools.test_tools import validate_proposed_patch_structure
        r = validate_proposed_patch_structure("--- a/f.py\n+++ b/f.py\n+new line\n")
        assert r.warnings   # no @@ header -> warning


# ===========================================================================
# test_tools — check_test_targets_exist
# ===========================================================================

class TestCheckTestTargetsExist:

    def _make_case(self, target_file):
        from agent.tools.test_tools import TestCase
        return TestCase(
            objective="test", target_file=target_file, target_func="f",
            test_type="unit", input_data="x", expected="y", rationale="r",
        )

    def test_existing_file_no_warning(self):
        from agent.tools.test_tools import TestSuite, check_test_targets_exist
        suite = TestSuite(cases=[self._make_case("utils.py")])
        r = check_test_targets_exist(suite, str(SAMPLE_REPO))
        assert not r.issues

    def test_missing_file_warns(self):
        from agent.tools.test_tools import TestSuite, check_test_targets_exist
        suite = TestSuite(cases=[self._make_case("nonexistent_file.py")])
        r = check_test_targets_exist(suite, str(SAMPLE_REPO))
        assert r.warnings

    def test_traversal_detected(self):
        from agent.tools.test_tools import TestSuite, check_test_targets_exist
        suite = TestSuite(cases=[self._make_case("../../../etc/passwd")])
        r = check_test_targets_exist(suite, str(SAMPLE_REPO))
        assert not r.valid
        assert r.issues

    def test_invalid_repo_root_warns(self, tmp_path):
        from agent.tools.test_tools import TestSuite, check_test_targets_exist
        suite = TestSuite(cases=[self._make_case("utils.py")])
        r = check_test_targets_exist(suite, "/does/not/exist")
        assert r.warnings


# ===========================================================================
# test_generator node
# ===========================================================================

class TestTestGeneratorNode:

    def test_runs_with_stub_llm(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.test_generator import test_generator
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = test_generator(_full_state())
        _restore_llm_cache()
        assert "generated_tests" in result
        assert result["generated_tests"] is not None

    def test_generated_tests_is_string(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.test_generator import test_generator
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = test_generator(_full_state())
        _restore_llm_cache()
        assert isinstance(result["generated_tests"], str)

    def test_generated_tests_has_test_function(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.test_generator import test_generator
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = test_generator(_full_state())
        _restore_llm_cache()
        assert "def test_" in result["generated_tests"]

    def test_test_results_not_executed_sentinel(self, monkeypatch):
        """test_generator must NOT claim tests passed — sentinel required."""
        _clear_llm_cache(monkeypatch)
        from agent.nodes.test_generator import test_generator
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = test_generator(_full_state())
        _restore_llm_cache()
        tr = result["test_results"]
        assert tr is not None
        assert "[NOT EXECUTED]" in tr["output"], (
            f"test_results output must contain NOT EXECUTED sentinel, got: {tr['output']!r}"
        )

    def test_test_results_passed_count_zero(self, monkeypatch):
        """test_generator must never report passed > 0 without execution."""
        _clear_llm_cache(monkeypatch)
        from agent.nodes.test_generator import test_generator
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = test_generator(_full_state())
        _restore_llm_cache()
        assert result["test_results"]["passed"] == 0

    def test_next_stage_is_verification(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.test_generator import test_generator
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = test_generator(_full_state())
        _restore_llm_cache()
        assert result["current_stage"] == "verification"

    def test_works_without_root_cause(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.test_generator import test_generator
        state = _full_state()
        state["root_cause"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = test_generator(state)
        _restore_llm_cache()
        assert result["generated_tests"] is not None

    def test_works_without_fix_plan(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.test_generator import test_generator
        state = _full_state()
        state["fix_plan"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = test_generator(state)
        _restore_llm_cache()
        assert result["generated_tests"] is not None

    def test_works_without_code_diff(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.test_generator import test_generator
        state = _full_state()
        state["code_diff"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = test_generator(state)
        _restore_llm_cache()
        assert result["generated_tests"] is not None

    def test_no_files_written(self, monkeypatch, tmp_path):
        """test_generator must never write files."""
        _clear_llm_cache(monkeypatch)
        from agent.nodes.test_generator import test_generator
        state = _full_state(str(tmp_path))
        before = set(tmp_path.rglob("*"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            test_generator(state)
        after = set(tmp_path.rglob("*"))
        _restore_llm_cache()
        assert before == after, f"test_generator wrote files: {after - before}"


class TestMakeStubPytest:
    """Unit tests for the stub pytest generator (no LLM)."""

    def test_produces_test_function(self):
        from agent.nodes.test_generator import _make_stub_pytest
        source = _make_stub_pytest([], "some bug")
        assert "def test_" in source

    def test_no_cases_produces_placeholder(self):
        from agent.nodes.test_generator import _make_stub_pytest
        source = _make_stub_pytest([], "bug")
        assert "placeholder" in source.lower() or "TODO" in source

    def test_with_cases_uses_objective(self):
        from agent.tools.test_tools import TestCase
        from agent.nodes.test_generator import _make_stub_pytest
        case = TestCase(
            objective="verify bounds check", target_file="utils.py",
            target_func="get_items", test_type="regression",
            input_data="[]", expected="None", rationale="fixes bug",
        )
        source = _make_stub_pytest([case], "bug")
        assert "def test_" in source
        assert "verify" in source.lower() or "bounds" in source.lower()

    def test_valid_python_syntax(self):
        import ast as _ast
        from agent.nodes.test_generator import _make_stub_pytest
        source = _make_stub_pytest([], "some bug with\nnewlines")
        _ast.parse(source)   # must not raise


# ===========================================================================
# verifier node
# ===========================================================================

class TestVerifierNode:

    def _state_with_tests(self, repo_path: str = "") -> dict:
        state = _full_state(repo_path)
        state["generated_tests"] = (
            "import pytest\n\n"
            "def test_get_items_empty_list():\n"
            "    from utils import get_items\n"
            "    result = get_items([], 0)\n"
            "    assert result is None\n"
        )
        state["test_results"] = {
            "passed": 0, "failed": 0, "errors": 0,
            "output": "[NOT EXECUTED] Tests were generated but not run.",
        }
        return state

    def test_runs_with_stub_llm(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(self._state_with_tests())
        _restore_llm_cache()
        assert "verification_report" in result
        assert result["verification_report"] is not None

    def test_report_has_required_fields(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(self._state_with_tests())
        _restore_llm_cache()
        vr = result["verification_report"]
        for field in ("bug_summary", "root_cause_summary", "fix_description",
                      "diff", "test_results", "confidence_score", "status"):
            assert field in vr, f"Missing field: {field}"

    def test_confidence_score_in_range(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(self._state_with_tests())
        _restore_llm_cache()
        conf = result["verification_report"]["confidence_score"]
        assert 0.0 <= conf <= 1.0

    def test_never_claims_tests_passed(self, monkeypatch):
        """Verifier must preserve the NOT_EXECUTED sentinel."""
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(self._state_with_tests())
        _restore_llm_cache()
        tr = result["verification_report"]["test_results"]
        assert "[NOT EXECUTED]" in tr["output"], (
            "Verifier overwrote the NOT_EXECUTED sentinel — this is a bug."
        )

    def test_never_claims_tests_passed_when_test_results_none(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        state = self._state_with_tests()
        state["test_results"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(state)
        _restore_llm_cache()
        tr = result["verification_report"]["test_results"]
        assert tr["passed"] == 0
        assert "[NOT EXECUTED]" in tr["output"]

    def test_status_partial_with_valid_inputs(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(self._state_with_tests())
        _restore_llm_cache()
        # "success" requires actual execution; expect "partial" or "failed"
        assert result["verification_report"]["status"] in ("partial", "failed")

    def test_empty_diff_produces_issues(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        state = self._state_with_tests()
        state["code_diff"] = ""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(state)
        _restore_llm_cache()
        # Empty diff is an issue → status should be "failed"
        assert result["verification_report"]["status"] == "failed"

    def test_broken_test_syntax_reported(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        state = self._state_with_tests()
        state["generated_tests"] = "def bad_test(:\n    pass\n"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(state)
        _restore_llm_cache()
        # Broken syntax must produce an issue → status failed
        assert result["verification_report"]["status"] == "failed"

    def test_works_without_root_cause(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        state = self._state_with_tests()
        state["root_cause"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(state)
        _restore_llm_cache()
        assert result["verification_report"] is not None

    def test_works_without_fix_plan(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        state = self._state_with_tests()
        state["fix_plan"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(state)
        _restore_llm_cache()
        assert result["verification_report"] is not None

    def test_next_stage_is_verification(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = verifier(self._state_with_tests())
        _restore_llm_cache()
        assert result["current_stage"] == "verification"

    def test_no_files_written(self, monkeypatch, tmp_path):
        """verifier must never write files."""
        _clear_llm_cache(monkeypatch)
        from agent.nodes.verifier import verifier
        state = self._state_with_tests(str(tmp_path))
        before = set(tmp_path.rglob("*"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            verifier(state)
        after = set(tmp_path.rglob("*"))
        _restore_llm_cache()
        assert before == after


class TestComputeConfidence:
    """Unit tests for the deterministic confidence scorer."""

    def test_zero_when_all_missing(self):
        from agent.nodes.verifier import _compute_confidence
        assert _compute_confidence(0.0, False, False, ["issue"]) == 0.0

    def test_max_when_all_present(self):
        from agent.nodes.verifier import _compute_confidence
        score = _compute_confidence(1.0, True, True, [])
        assert score == 1.0

    def test_partial_score(self):
        from agent.nodes.verifier import _compute_confidence
        # 0.85 * 0.4 + 0.3 + 0.2 + 0.1 = 0.34 + 0.6 = 0.94
        score = _compute_confidence(0.85, True, True, [])
        assert 0.90 <= score <= 1.0

    def test_score_capped_at_one(self):
        from agent.nodes.verifier import _compute_confidence
        score = _compute_confidence(1.0, True, True, [])
        assert score <= 1.0

    def test_issues_reduce_score(self):
        from agent.nodes.verifier import _compute_confidence
        with_issues    = _compute_confidence(0.8, True, True, ["an issue"])
        without_issues = _compute_confidence(0.8, True, True, [])
        assert with_issues < without_issues
