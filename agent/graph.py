"""
agent/graph.py
---------------
LangGraph pipeline definition for Pitchproof.

Pipeline order:
    repo_analyzer → root_cause → fix_planner → code_fixer → test_generator → verifier

Usage:
    from agent.graph import build_graph

    graph = build_graph()
    result = graph.invoke({
        "bug_report": "IndexError at utils.py line 42",
        "repo_url":   "https://github.com/org/repo",
        "current_stage": "repo_analysis",
        "errors": [],
        # all Optional fields default to None (not required at invocation)
    })
    print(result["verification_report"])

The graph is built fresh each call to build_graph() so it can be safely
recreated per-request in the FastAPI background task.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from agent.state import PitchproofState
from agent.nodes.repo_analyzer  import repo_analyzer
from agent.nodes.root_cause     import root_cause
from agent.nodes.fix_planner    import fix_planner
from agent.nodes.code_fixer     import code_fixer
from agent.nodes.test_generator import test_generator
from agent.nodes.verifier       import verifier


# Node name constants — used in tests and the frontend stage tracker
NODE_REPO_ANALYZER  = "repo_analyzer"
NODE_ROOT_CAUSE     = "root_cause"
NODE_FIX_PLANNER    = "fix_planner"
NODE_CODE_FIXER     = "code_fixer"
NODE_TEST_GENERATOR = "test_generator"
NODE_VERIFIER       = "verifier"

# Ordered list matching PIPELINE_STAGES in agent/state.py
ORDERED_NODES = [
    NODE_REPO_ANALYZER,
    NODE_ROOT_CAUSE,
    NODE_FIX_PLANNER,
    NODE_CODE_FIXER,
    NODE_TEST_GENERATOR,
    NODE_VERIFIER,
]


def build_graph() -> StateGraph:
    """
    Construct and compile the Pitchproof LangGraph pipeline.

    Returns a compiled graph that accepts PitchproofState as input and
    returns a fully-populated PitchproofState when invoked.

    Each node function (agent/nodes/*.py) receives the full current state
    and returns a *partial* dict with only the fields it owns.
    LangGraph merges the partial update back into the running state.
    """
    workflow = StateGraph(PitchproofState)

    # ── Register nodes ────────────────────────────────────────────────────
    workflow.add_node(NODE_REPO_ANALYZER,  repo_analyzer)
    workflow.add_node(NODE_ROOT_CAUSE,     root_cause)
    workflow.add_node(NODE_FIX_PLANNER,    fix_planner)
    workflow.add_node(NODE_CODE_FIXER,     code_fixer)
    workflow.add_node(NODE_TEST_GENERATOR, test_generator)
    workflow.add_node(NODE_VERIFIER,       verifier)

    # ── Define edges (sequential pipeline) ───────────────────────────────
    workflow.set_entry_point(NODE_REPO_ANALYZER)

    workflow.add_edge(NODE_REPO_ANALYZER,  NODE_ROOT_CAUSE)
    workflow.add_edge(NODE_ROOT_CAUSE,     NODE_FIX_PLANNER)
    workflow.add_edge(NODE_FIX_PLANNER,    NODE_CODE_FIXER)
    workflow.add_edge(NODE_CODE_FIXER,     NODE_TEST_GENERATOR)
    workflow.add_edge(NODE_TEST_GENERATOR, NODE_VERIFIER)
    workflow.add_edge(NODE_VERIFIER,       END)

    return workflow.compile()
