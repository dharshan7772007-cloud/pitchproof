"""
tests/test_agent_core.py
-------------------------
Tests for the Pitchproof agent core (graph construction + placeholder pass-through).

These tests do NOT require watsonx.ai or any external API credentials.
They verify:
  1. The graph can be constructed without errors.
  2. All six nodes are registered in the correct order.
  3. A minimal PitchproofState passes through the entire graph without crashing.
  4. Every expected output field is populated after a full graph run.
  5. The LLM abstraction falls back to StubLLMClient when no credentials are set.

Run with:
    pytest tests/test_agent_core.py -v
"""

from __future__ import annotations

import os
import sys

# Ensure project root is on the path when running from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agent.graph import build_graph, ORDERED_NODES, NODE_REPO_ANALYZER, NODE_VERIFIER
from agent.state import PitchproofState, PIPELINE_STAGES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_state() -> dict:
    """Return the minimum valid input state for the graph."""
    return {
        "bug_report":           "IndexError: list index out of range in utils.py at line 42",
        "repo_url":             "https://github.com/example/sample-repo",
        "repo_analysis":        None,
        "root_cause":           None,
        "fix_plan":             None,
        "code_diff":            None,
        "generated_tests":      None,
        "test_results":         None,
        "verification_report":  None,
        "current_stage":        "repo_analysis",
        "errors":               [],
    }


# ---------------------------------------------------------------------------
# Test 1 — Graph construction
# ---------------------------------------------------------------------------

def test_graph_builds_without_error():
    """build_graph() must return a compiled graph without raising."""
    graph = build_graph()
    assert graph is not None, "build_graph() returned None"


# ---------------------------------------------------------------------------
# Test 2 — Node ordering
# ---------------------------------------------------------------------------

def test_ordered_nodes_matches_pipeline_stages():
    """
    ORDERED_NODES in graph.py must align with PIPELINE_STAGES in state.py.
    The names may differ (node names vs stage names) but the count must match.
    """
    assert len(ORDERED_NODES) == len(PIPELINE_STAGES), (
        f"Node count {len(ORDERED_NODES)} != stage count {len(PIPELINE_STAGES)}"
    )


def test_ordered_nodes_starts_with_repo_analyzer():
    assert ORDERED_NODES[0] == NODE_REPO_ANALYZER


def test_ordered_nodes_ends_with_verifier():
    assert ORDERED_NODES[-1] == NODE_VERIFIER


def test_ordered_nodes_has_six_entries():
    assert len(ORDERED_NODES) == 6, f"Expected 6 nodes, got {len(ORDERED_NODES)}"


# ---------------------------------------------------------------------------
# Test 3 — Full graph pass-through (placeholder nodes)
# ---------------------------------------------------------------------------

def test_graph_runs_end_to_end():
    """
    Invoke the graph with a minimal state.
    All placeholder nodes must execute without raising.
    """
    graph = build_graph()
    result = graph.invoke(_minimal_state())
    assert result is not None, "Graph returned None"


def test_graph_populates_repo_analysis():
    graph = build_graph()
    result = graph.invoke(_minimal_state())
    assert result.get("repo_analysis") is not None, "repo_analysis was not populated"
    assert "suspect_files" in result["repo_analysis"]
    assert "language" in result["repo_analysis"]


def test_graph_populates_root_cause():
    graph = build_graph()
    result = graph.invoke(_minimal_state())
    assert result.get("root_cause") is not None, "root_cause was not populated"
    assert "explanation" in result["root_cause"]
    assert "confidence" in result["root_cause"]


def test_graph_populates_fix_plan():
    graph = build_graph()
    result = graph.invoke(_minimal_state())
    assert result.get("fix_plan") is not None, "fix_plan was not populated"
    assert isinstance(result["fix_plan"]["steps"], list)


def test_graph_populates_code_diff():
    graph = build_graph()
    result = graph.invoke(_minimal_state())
    assert result.get("code_diff") is not None, "code_diff was not populated"
    assert isinstance(result["code_diff"], str)


def test_graph_populates_generated_tests():
    graph = build_graph()
    result = graph.invoke(_minimal_state())
    assert result.get("generated_tests") is not None, "generated_tests was not populated"
    assert "def test_" in result["generated_tests"]


def test_graph_populates_test_results():
    graph = build_graph()
    result = graph.invoke(_minimal_state())
    tr = result.get("test_results")
    assert tr is not None, "test_results was not populated"
    assert "passed" in tr and "failed" in tr and "errors" in tr


def test_graph_populates_verification_report():
    graph = build_graph()
    result = graph.invoke(_minimal_state())
    vr = result.get("verification_report")
    assert vr is not None, "verification_report was not populated"
    assert "confidence_score" in vr
    assert "status" in vr
    assert "diff" in vr


def test_graph_preserves_bug_report_and_repo_url():
    """Inputs must survive unchanged through the full graph."""
    graph = build_graph()
    state = _minimal_state()
    result = graph.invoke(state)
    assert result["bug_report"] == state["bug_report"]
    assert result["repo_url"]   == state["repo_url"]


# ---------------------------------------------------------------------------
# Test 4 — LLM abstraction fallback
# ---------------------------------------------------------------------------

def test_stub_llm_used_when_no_credentials(monkeypatch):
    """
    When no credentials are set, get_llm_client() must return StubLLMClient
    and its invoke() must return a non-empty string.
    """
    # Clear any real credentials from the environment for this test
    for key in ("WATSONX_API_KEY", "WATSONX_PROJECT_ID", "OPENAI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(key, raising=False)

    # Clear the lru_cache so the factory re-evaluates
    from agent.llm import get_llm_client, StubLLMClient
    get_llm_client.cache_clear()

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        client = get_llm_client()

    assert isinstance(client, StubLLMClient), (
        f"Expected StubLLMClient, got {type(client).__name__}"
    )
    response = client.invoke("test prompt")
    assert isinstance(response, str) and len(response) > 0

    # Reset cache after test so other tests are not affected
    get_llm_client.cache_clear()


def test_stub_llm_is_available():
    from agent.llm import StubLLMClient
    assert StubLLMClient().is_available() is True
