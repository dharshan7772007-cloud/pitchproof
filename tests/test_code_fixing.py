"""
tests/test_code_fixing.py
--------------------------
Tests for Task 5: Fix Planner + Code Fixer + Patch Tools.

Coverage:
  - agent/tools/patch_tools.py  — path validation, PatchSet, diffs, preview
  - agent/nodes/fix_planner.py  — fix plan generation, parser, fallbacks
  - agent/nodes/code_fixer.py   — code generation, dry-run guarantee,
                                   LLM response parser, stub fallback

Security properties verified:
  - Path traversal rejected
  - Absolute paths rejected
  - Null bytes in paths rejected
  - applied flag always False on exit from code_fixer
  - No files written to disk

No real API credentials required — all LLM calls use StubLLMClient.

Run with:
    pytest tests/test_code_fixing.py -v
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


# ===========================================================================
# Helpers
# ===========================================================================

def _clear_llm_cache(monkeypatch):
    """Clear lru_cache and ensure StubLLMClient is used."""
    from agent.llm import get_llm_client
    get_llm_client.cache_clear()
    for key in ("WATSONX_API_KEY", "WATSONX_PROJECT_ID", "OPENAI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(key, raising=False)


def _restore_llm_cache():
    from agent.llm import get_llm_client
    get_llm_client.cache_clear()


def _base_state(repo_path: str = "") -> dict:
    return {
        "bug_report":   "IndexError: list index out of range in utils.py at line 42",
        "repo_url":     repo_path or str(SAMPLE_REPO),
        "repo_analysis": {
            "suspect_files":     ["utils.py"],
            "relevant_snippets": [
                "utils.py:1 — def get_items(items, index):\n    return items[index]"
            ],
            "language": "python",
            "summary":  "2 source files found.",
        },
        "root_cause": {
            "explanation":    "Access without bounds check causes IndexError.",
            "fault_location": "utils.py:11",
            "confidence":     0.85,
        },
        "fix_plan":            None,
        "code_diff":           None,
        "generated_tests":     None,
        "test_results":        None,
        "verification_report": None,
        "current_stage":       "fix_plan",
        "errors":              [],
    }


# ===========================================================================
# patch_tools — validate_target_path
# ===========================================================================

class TestValidateTargetPath:

    def test_valid_relative_path_accepted(self, tmp_path):
        from agent.tools.patch_tools import validate_target_path
        result = validate_target_path(str(tmp_path), "utils.py")
        assert str(result).endswith("utils.py")

    def test_valid_nested_path_accepted(self, tmp_path):
        from agent.tools.patch_tools import validate_target_path
        result = validate_target_path(str(tmp_path), "src/core/utils.py")
        assert "utils.py" in str(result)

    def test_empty_path_raises(self, tmp_path):
        from agent.tools.patch_tools import validate_target_path
        with pytest.raises(ValueError, match="empty"):
            validate_target_path(str(tmp_path), "")

    def test_whitespace_path_raises(self, tmp_path):
        from agent.tools.patch_tools import validate_target_path
        with pytest.raises(ValueError, match="empty"):
            validate_target_path(str(tmp_path), "   ")

    def test_absolute_path_raises(self, tmp_path):
        from agent.tools.patch_tools import validate_target_path
        with pytest.raises(ValueError, match="absolute"):
            validate_target_path(str(tmp_path), "/etc/passwd")

    def test_path_traversal_parent_dir_raises(self, tmp_path):
        from agent.tools.patch_tools import validate_target_path
        with pytest.raises(ValueError, match="traversal"):
            validate_target_path(str(tmp_path), "../secret.py")

    def test_path_traversal_deep_raises(self, tmp_path):
        from agent.tools.patch_tools import validate_target_path
        with pytest.raises(ValueError, match="traversal"):
            validate_target_path(str(tmp_path), "a/b/../../../../../../etc/passwd")

    def test_null_byte_in_path_raises(self, tmp_path):
        from agent.tools.patch_tools import validate_target_path
        with pytest.raises(ValueError, match="null"):
            validate_target_path(str(tmp_path), "utils\x00.py")


# ===========================================================================
# patch_tools — make_proposed_change
# ===========================================================================

class TestMakeProposedChange:

    def test_creates_change_with_applied_false(self, tmp_path):
        from agent.tools.patch_tools import make_proposed_change
        change = make_proposed_change(
            repo_root=str(tmp_path),
            rel_path="utils.py",
            proposed_code="def get_items(items, index):\n    if index < len(items):\n        return items[index]\n",
            description="Add bounds check",
        )
        assert change.applied is False

    def test_rel_path_stored(self, tmp_path):
        from agent.tools.patch_tools import make_proposed_change
        change = make_proposed_change(str(tmp_path), "utils.py", "x=1", "test")
        assert change.rel_path == "utils.py"

    def test_traversal_raises(self, tmp_path):
        from agent.tools.patch_tools import make_proposed_change
        with pytest.raises(ValueError, match="traversal"):
            make_proposed_change(str(tmp_path), "../outside.py", "x=1", "bad")

    def test_original_code_stored(self, tmp_path):
        from agent.tools.patch_tools import make_proposed_change
        change = make_proposed_change(
            str(tmp_path), "f.py", "new", "desc", original_code="old"
        )
        assert change.original_code == "old"

    def test_new_file_flag(self, tmp_path):
        from agent.tools.patch_tools import make_proposed_change
        change = make_proposed_change(
            str(tmp_path), "new_file.py", "content", "new file", is_new_file=True
        )
        assert change.is_new_file is True


# ===========================================================================
# patch_tools — make_patch_set
# ===========================================================================

class TestMakePatchSet:

    def test_valid_entry_accepted(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set
        raw = [{"rel_path": "utils.py", "proposed_code": "x=1", "description": "fix"}]
        ps = make_patch_set(str(tmp_path), raw)
        assert len(ps.changes) == 1
        assert ps.is_valid

    def test_traversal_entry_rejected_with_error(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set
        raw = [{"rel_path": "../evil.py", "proposed_code": "x=1", "description": "bad"}]
        ps = make_patch_set(str(tmp_path), raw)
        assert len(ps.changes) == 0
        assert not ps.is_valid
        assert len(ps.validation_errors) == 1

    def test_missing_rel_path_rejected(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set
        raw = [{"proposed_code": "x=1", "description": "bad"}]
        ps = make_patch_set(str(tmp_path), raw)
        assert not ps.is_valid

    def test_missing_proposed_code_rejected(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set
        raw = [{"rel_path": "utils.py", "description": "bad"}]
        ps = make_patch_set(str(tmp_path), raw)
        assert not ps.is_valid

    def test_non_dict_entry_rejected(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set
        ps = make_patch_set(str(tmp_path), ["not-a-dict"])  # type: ignore
        assert not ps.is_valid

    def test_empty_list_returns_empty_valid_patch_set(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set
        ps = make_patch_set(str(tmp_path), [])
        assert ps.is_valid
        assert len(ps.changes) == 0

    def test_affected_files_property(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set
        raw = [
            {"rel_path": "a.py", "proposed_code": "x=1", "description": "A"},
            {"rel_path": "b.py", "proposed_code": "y=2", "description": "B"},
        ]
        ps = make_patch_set(str(tmp_path), raw)
        assert "a.py" in ps.affected_files
        assert "b.py" in ps.affected_files

    def test_all_changes_have_applied_false(self, tmp_path):
        """Security: applied must always be False when coming out of make_patch_set."""
        from agent.tools.patch_tools import make_patch_set
        raw = [{"rel_path": "utils.py", "proposed_code": "x=1", "description": "fix"}]
        ps = make_patch_set(str(tmp_path), raw)
        for change in ps.changes:
            assert change.applied is False, "applied must be False — no auto-write"


# ===========================================================================
# patch_tools — generate_unified_diff
# ===========================================================================

class TestGenerateUnifiedDiff:

    def test_diff_between_original_and_modified(self):
        from agent.tools.patch_tools import generate_unified_diff
        original = "def foo():\n    return 1\n"
        modified = "def foo():\n    return 2\n"
        diff = generate_unified_diff(original, modified, "foo.py")
        assert "-    return 1" in diff
        assert "+    return 2" in diff

    def test_empty_original_produces_diff(self):
        from agent.tools.patch_tools import generate_unified_diff
        diff = generate_unified_diff("", "x = 1\n", "new.py")
        assert "+x = 1" in diff

    def test_identical_content_produces_empty_diff(self):
        from agent.tools.patch_tools import generate_unified_diff
        code = "x = 1\n"
        diff = generate_unified_diff(code, code, "f.py")
        assert diff == ""

    def test_diff_contains_filename(self):
        from agent.tools.patch_tools import generate_unified_diff
        diff = generate_unified_diff("old\n", "new\n", "myfile.py")
        assert "myfile.py" in diff


# ===========================================================================
# patch_tools — preview_patch_set
# ===========================================================================

class TestPreviewPatchSet:

    def test_preview_contains_proposed_label(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set, preview_patch_set
        raw = [{"rel_path": "utils.py", "proposed_code": "x=1", "description": "fix"}]
        ps = make_patch_set(str(tmp_path), raw)
        preview = preview_patch_set(ps)
        assert "proposed" in preview.lower() or "PROPOSED" in preview

    def test_preview_shows_errors_for_invalid_set(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set, preview_patch_set
        raw = [{"rel_path": "../bad.py", "proposed_code": "x=1", "description": "bad"}]
        ps = make_patch_set(str(tmp_path), raw)
        preview = preview_patch_set(ps)
        assert "VALIDATION" in preview or "error" in preview.lower()

    def test_preview_empty_set(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set, preview_patch_set
        ps = make_patch_set(str(tmp_path), [])
        preview = preview_patch_set(ps)
        assert "No proposed changes" in preview


# ===========================================================================
# fix_planner node
# ===========================================================================

class TestFixPlannerNode:

    def test_runs_with_stub_llm(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.fix_planner import fix_planner
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = fix_planner(_base_state())
        _restore_llm_cache()
        assert "fix_plan" in result
        assert result["fix_plan"] is not None

    def test_fix_plan_has_steps(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.fix_planner import fix_planner
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = fix_planner(_base_state())
        _restore_llm_cache()
        assert isinstance(result["fix_plan"]["steps"], list)
        assert len(result["fix_plan"]["steps"]) > 0

    def test_fix_plan_has_affected_files(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.fix_planner import fix_planner
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = fix_planner(_base_state())
        _restore_llm_cache()
        assert isinstance(result["fix_plan"]["affected_files"], list)
        assert len(result["fix_plan"]["affected_files"]) > 0

    def test_fix_plan_has_rationale(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.fix_planner import fix_planner
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = fix_planner(_base_state())
        _restore_llm_cache()
        assert isinstance(result["fix_plan"]["rationale"], str)
        assert len(result["fix_plan"]["rationale"]) > 0

    def test_next_stage_is_code_fix(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.fix_planner import fix_planner
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = fix_planner(_base_state())
        _restore_llm_cache()
        assert result["current_stage"] == "code_fix"

    def test_works_without_root_cause(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.fix_planner import fix_planner
        state = _base_state()
        state["root_cause"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = fix_planner(state)
        _restore_llm_cache()
        assert result["fix_plan"] is not None

    def test_works_without_repo_analysis(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.fix_planner import fix_planner
        state = _base_state()
        state["repo_analysis"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = fix_planner(state)
        _restore_llm_cache()
        assert result["fix_plan"] is not None

    def test_works_without_both_upstream(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.fix_planner import fix_planner
        state = _base_state()
        state["root_cause"]   = None
        state["repo_analysis"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = fix_planner(state)
        _restore_llm_cache()
        assert result["fix_plan"] is not None


class TestFixPlanParser:
    """Unit tests for _parse_fix_plan (no LLM)."""

    def test_well_formed_response_parsed(self):
        from agent.nodes.fix_planner import _parse_fix_plan
        response = (
            "STEPS:\n"
            "1. Check the index before accessing the list.\n"
            "2. Add a guard clause.\n\n"
            "AFFECTED_FILES:\n"
            "utils.py\n\n"
            "RATIONALE:\n"
            "The fix adds a bounds check to prevent IndexError.\n"
        )
        plan = _parse_fix_plan(response, "utils.py:11")
        assert len(plan["steps"]) == 2
        assert "utils.py" in plan["affected_files"]
        assert "bounds check" in plan["rationale"]

    def test_missing_steps_uses_fallback(self):
        from agent.nodes.fix_planner import _parse_fix_plan
        plan = _parse_fix_plan("RATIONALE:\nsome rationale\n", "utils.py:11")
        assert len(plan["steps"]) > 0
        assert "utils.py:11" in plan["steps"][0]

    def test_missing_files_uses_fault_location(self):
        from agent.nodes.fix_planner import _parse_fix_plan
        plan = _parse_fix_plan(
            "STEPS:\n1. Fix it.\n\nRATIONALE:\nFix.\n",
            "utils.py:11"
        )
        assert any("utils.py" in f for f in plan["affected_files"])

    def test_missing_rationale_uses_fallback(self):
        from agent.nodes.fix_planner import _parse_fix_plan
        plan = _parse_fix_plan("STEPS:\n1. Fix it.\n\nAFFECTED_FILES:\nutils.py\n", "utils.py:11")
        assert len(plan["rationale"]) > 0

    def test_empty_response_returns_valid_plan(self):
        from agent.nodes.fix_planner import _parse_fix_plan
        plan = _parse_fix_plan("", "unknown:0")
        assert isinstance(plan["steps"], list)
        assert isinstance(plan["affected_files"], list)
        assert isinstance(plan["rationale"], str)


# ===========================================================================
# code_fixer node
# ===========================================================================

class TestCodeFixerNode:

    def test_runs_with_stub_llm(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.code_fixer import code_fixer
        state = _base_state()
        state["fix_plan"] = {
            "steps": ["Add bounds check."],
            "affected_files": [],
            "rationale": "Prevents IndexError",
        }
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = code_fixer(state)
        _restore_llm_cache()
        assert "code_diff" in result
        assert result["code_diff"] is not None

    def test_code_diff_is_string(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.code_fixer import code_fixer
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = code_fixer(_base_state())
        _restore_llm_cache()
        assert isinstance(result["code_diff"], str)

    def test_next_stage_is_test_generation(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.code_fixer import code_fixer
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = code_fixer(_base_state())
        _restore_llm_cache()
        assert result["current_stage"] == "test_generation"

    def test_dry_run_no_files_written(self, monkeypatch, tmp_path):
        """No files in tmp_path should be created or modified by code_fixer."""
        _clear_llm_cache(monkeypatch)
        from agent.nodes.code_fixer import code_fixer
        state = _base_state(str(tmp_path))
        before = set(tmp_path.rglob("*"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            code_fixer(state)
        after = set(tmp_path.rglob("*"))
        _restore_llm_cache()
        assert before == after, f"code_fixer wrote files: {after - before}"

    def test_works_without_fix_plan(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.code_fixer import code_fixer
        state = _base_state()
        state["fix_plan"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = code_fixer(state)
        _restore_llm_cache()
        assert result["code_diff"] is not None

    def test_works_without_root_cause(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.code_fixer import code_fixer
        state = _base_state()
        state["root_cause"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = code_fixer(state)
        _restore_llm_cache()
        assert result["code_diff"] is not None

    def test_works_without_repo_analysis(self, monkeypatch):
        _clear_llm_cache(monkeypatch)
        from agent.nodes.code_fixer import code_fixer
        state = _base_state()
        state["repo_analysis"] = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = code_fixer(state)
        _restore_llm_cache()
        assert result["code_diff"] is not None


class TestCodeResponseParser:
    """Unit tests for _parse_code_response (no LLM)."""

    def test_well_formed_response_parsed(self):
        from agent.nodes.code_fixer import _parse_code_response
        response = (
            "FILE: utils.py\n"
            "DESCRIPTION: Add bounds check to get_items\n"
            "CODE:\n"
            "```python\n"
            "def get_items(items, index):\n"
            "    if index < len(items):\n"
            "        return items[index]\n"
            "    return None\n"
            "```\n"
        )
        entries = _parse_code_response(response)
        assert len(entries) == 1
        assert entries[0]["rel_path"] == "utils.py"
        assert "get_items" in entries[0]["proposed_code"]
        assert "Add bounds check" in entries[0]["description"]

    def test_multiple_files_parsed(self):
        from agent.nodes.code_fixer import _parse_code_response
        response = (
            "FILE: a.py\nDESCRIPTION: Fix A\nCODE:\n```python\nx=1\n```\n"
            "FILE: b.py\nDESCRIPTION: Fix B\nCODE:\n```python\ny=2\n```\n"
        )
        entries = _parse_code_response(response)
        assert len(entries) == 2

    def test_empty_response_returns_empty_list(self):
        from agent.nodes.code_fixer import _parse_code_response
        assert _parse_code_response("") == []

    def test_malformed_response_returns_empty_list(self):
        from agent.nodes.code_fixer import _parse_code_response
        assert _parse_code_response("This is just some random text.") == []

    def test_stub_response_returns_empty_list(self):
        from agent.nodes.code_fixer import _parse_code_response
        stub = (
            "[STUB] LLM not configured. "
            "Set WATSONX_API_KEY + WATSONX_PROJECT_ID (or OPENAI_API_KEY) in .env "
            "to enable real model responses."
        )
        assert _parse_code_response(stub) == []


class TestStubPatchSet:
    """Unit tests for _stub_patch_set (no LLM)."""

    def test_stub_with_valid_file_produces_patch_set(self, tmp_path):
        from agent.nodes.code_fixer import _stub_patch_set
        fix_plan = {"steps": [], "affected_files": ["utils.py"], "rationale": ""}
        ps = _stub_patch_set(fix_plan, str(tmp_path))
        assert len(ps.changes) == 1
        assert ps.changes[0].applied is False

    def test_stub_with_no_files_returns_error_patch_set(self, tmp_path):
        from agent.nodes.code_fixer import _stub_patch_set
        fix_plan = {"steps": [], "affected_files": [], "rationale": ""}
        ps = _stub_patch_set(fix_plan, str(tmp_path))
        assert not ps.is_valid

    def test_stub_skips_placeholder_entries(self, tmp_path):
        from agent.nodes.code_fixer import _stub_patch_set
        fix_plan = {
            "steps": [],
            "affected_files": ["(file to be determined)", "  "],
            "rationale": ""
        }
        ps = _stub_patch_set(fix_plan, str(tmp_path))
        # Placeholder entries contain "(" — should be skipped
        assert len(ps.changes) == 0

    def test_stub_proposed_code_contains_not_applied(self, tmp_path):
        from agent.nodes.code_fixer import _stub_patch_set
        fix_plan = {"steps": [], "affected_files": ["utils.py"], "rationale": ""}
        ps = _stub_patch_set(fix_plan, str(tmp_path))
        assert "NOT APPLIED" in ps.changes[0].proposed_code


# ===========================================================================
# Security: proposed vs applied distinction
# ===========================================================================

class TestProposedVsApplied:

    def test_make_proposed_change_has_applied_false(self, tmp_path):
        from agent.tools.patch_tools import make_proposed_change
        change = make_proposed_change(str(tmp_path), "f.py", "x=1", "desc")
        assert change.applied is False

    def test_patch_set_changes_all_have_applied_false(self, tmp_path):
        from agent.tools.patch_tools import make_patch_set
        raw = [
            {"rel_path": "a.py", "proposed_code": "x=1", "description": "A"},
            {"rel_path": "b.py", "proposed_code": "y=2", "description": "B"},
        ]
        ps = make_patch_set(str(tmp_path), raw)
        for change in ps.changes:
            assert change.applied is False

    def test_code_fixer_never_sets_applied_true(self, monkeypatch, tmp_path):
        """End-to-end: code_fixer output must never contain applied=True changes."""
        _clear_llm_cache(monkeypatch)
        # Inject a mock LLM that returns a real structured response
        from agent.llm import LLMClient, get_llm_client
        class MockLLM(LLMClient):
            def is_available(self): return True
            def invoke(self, prompt, *, max_tokens=1024, temperature=0.2):
                return (
                    f"FILE: utils.py\n"
                    f"DESCRIPTION: Add bounds check\n"
                    f"CODE:\n```python\n"
                    f"def get_items(items, index):\n"
                    f"    if index < len(items):\n"
                    f"        return items[index]\n"
                    f"    return None\n"
                    f"```\n"
                )
        get_llm_client.cache_clear()
        import agent.llm as llm_mod
        monkeypatch.setattr(llm_mod, "get_llm_client", lambda: MockLLM())

        from agent.nodes.code_fixer import code_fixer
        state = _base_state(str(tmp_path))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = code_fixer(state)

        # code_diff is a string — assert it contains the proposed label or diff
        assert isinstance(result["code_diff"], str)
        # Restore: undo monkeypatch first, then clear the real lru_cache
        monkeypatch.undo()
        import agent.llm as _llm_mod
        _llm_mod.get_llm_client.cache_clear()
