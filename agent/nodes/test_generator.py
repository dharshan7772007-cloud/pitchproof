"""
agent/nodes/test_generator.py
------------------------------
Node 5 of 6 — Test Generation.

Consumes root_cause, fix_plan, and code_diff from PitchproofState, calls the
LLM to produce structured test cases (as TestCase objects) plus a runnable
pytest file, and validates the output via test_tools.

IMPORTANT — this node generates tests; it does NOT execute them.
  - state["generated_tests"] holds the pytest source as a string.
  - state["test_results"] is set to a "not executed" stub so downstream
    nodes are never misled into believing tests have been run.

Works with StubLLMClient when no LLM credentials are configured.

Reads:   state["root_cause"], state["fix_plan"], state["code_diff"],
         state["bug_report"], state["repo_analysis"]
Writes:  state["generated_tests"], state["test_results"], state["current_stage"]
"""

from __future__ import annotations

import re
from typing import List, Optional

from agent.llm import get_llm_client
from agent.state import (
    FixPlan, PitchproofState, RepoAnalysis, RootCause, TestResults,
)
from agent.tools.test_tools import (
    TestCase,
    TestSuite,
    parse_test_cases_from_text,
    validate_test_suite,
)

# Sentinel value: tests exist but have NOT been executed
_NOT_EXECUTED_OUTPUT = (
    "[NOT EXECUTED] Tests were generated but not run. "
    "An authorised execution step is required to obtain real results."
)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_test_case_prompt(
    bug_report: str,
    root_cause: RootCause,
    fix_plan: FixPlan,
    code_diff: str,
) -> str:
    """
    Ask the LLM to produce structured test case descriptions (no code yet).
    Structured format so test_tools.parse_test_cases_from_text() can parse it.
    """
    affected = ", ".join(fix_plan.get("affected_files") or []) or "unknown"
    steps_block = "\n".join(
        f"  {i+1}. {s}" for i, s in enumerate(fix_plan.get("steps") or [])
    ) or "  (none)"
    diff_excerpt = (code_diff or "")[:600] + (
        "\n... (truncated)" if len(code_diff or "") > 600 else ""
    )

    return f"""You are an expert software engineer writing regression tests for a bug fix.

## Bug Report
{bug_report}

## Root Cause
{root_cause.get('explanation', 'unknown')}
Fault Location: {root_cause.get('fault_location', 'unknown')}

## Fix Plan
Files changed: {affected}
Steps:
{steps_block}

## Proposed Diff (excerpt)
{diff_excerpt or '(no diff available)'}

## Task
Generate 2–4 focused test cases that verify the fix works correctly and that
the original bug no longer occurs.

For each test case respond EXACTLY in this format:

TEST_CASE 1:
OBJECTIVE: <what this test checks>
TARGET_FILE: <relative/path/to/file.py>
TARGET_FUNC: <function or method under test>
TEST_TYPE: <regression | unit | edge_case | integration>
INPUT: <input value or precondition>
EXPECTED: <expected result or behaviour>
RATIONALE: <why this test validates the fix>

TEST_CASE 2:
...
"""


def _build_pytest_prompt(
    test_cases: List[TestCase],
    root_cause: RootCause,
    fix_plan: FixPlan,
    language: str,
) -> str:
    """
    Ask the LLM to convert structured TestCase descriptions into runnable pytest code.
    """
    cases_text = ""
    for i, case in enumerate(test_cases, 1):
        cases_text += (
            f"Test {i}: {case.objective}\n"
            f"  File: {case.target_file} / Function: {case.target_func}\n"
            f"  Input: {case.input_data}\n"
            f"  Expected: {case.expected}\n\n"
        )

    affected = ", ".join(fix_plan.get("affected_files") or []) or "unknown"

    return f"""You are an expert {language} developer writing pytest tests.

## Tests to implement
{cases_text}

## Context
- Fault location: {root_cause.get('fault_location', 'unknown')}
- Files changed by fix: {affected}

## Task
Write a complete, runnable pytest file implementing the tests above.

Rules:
- Import only from the standard library or from the files listed as changed.
- Use pytest conventions (functions named test_*).
- Add a brief docstring to each test function.
- Do NOT use unittest.TestCase.
- Do NOT use any external fixtures not defined in the file.

Output the pytest file content ONLY, inside a code block:

```python
<complete pytest file>
```
"""


# ---------------------------------------------------------------------------
# LLM response parsers
# ---------------------------------------------------------------------------

_PYTEST_CODE_RE = re.compile(
    r"```(?:python|py)?\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def _extract_pytest_source(response: str) -> str:
    """Extract the first ```python ... ``` block from an LLM response."""
    match = _PYTEST_CODE_RE.search(response)
    if match:
        return match.group(1).rstrip()
    return ""


def _make_stub_pytest(test_cases: List[TestCase], bug_report: str) -> str:
    """
    Generate a minimal placeholder pytest file when the LLM cannot produce code.
    Always contains at least one test_* function so pytest can discover it.
    """
    lines = [
        "# [GENERATED — NOT EXECUTED]",
        "# Stub test file generated when LLM code output was not available.",
        f"# Bug: {bug_report[:120].replace(chr(10), ' ')}",
        "",
        "import pytest",
        "",
    ]
    if not test_cases:
        lines += [
            "def test_placeholder_no_cases():",
            '    """Placeholder: no test cases were generated."""',
            "    # TODO: implement after configuring a real LLM provider",
            "    pass",
        ]
    else:
        for i, case in enumerate(test_cases, 1):
            func_name = re.sub(r"[^a-z0-9_]", "_", case.objective.lower())[:60].strip("_")
            func_name = func_name or f"test_case_{i}"
            if not func_name.startswith("test_"):
                func_name = f"test_{func_name}"
            lines += [
                f"def {func_name}():",
                f'    """{case.objective}',
                f"    Target: {case.target_file}::{case.target_func}",
                f'    Expected: {case.expected}"""',
                f"    # TODO: implement — {case.rationale}",
                "    pass",
                "",
            ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def test_generator(state: PitchproofState) -> dict:
    """
    Generate test cases and a pytest source file for the proposed fix.

    This node generates tests; it does NOT execute them.
    test_results is set to a "not executed" sentinel.

    Reads:   state["root_cause"], state["fix_plan"], state["code_diff"],
             state["bug_report"], state["repo_analysis"]
    Writes:  state["generated_tests"], state["test_results"], state["current_stage"]
    """
    bug_report:    str                     = state.get("bug_report", "")
    root_cause:    Optional[RootCause]    = state.get("root_cause")
    fix_plan:      Optional[FixPlan]       = state.get("fix_plan")
    code_diff:     Optional[str]           = state.get("code_diff", "")
    repo_analysis: Optional[RepoAnalysis] = state.get("repo_analysis")

    # ── Graceful fallbacks ────────────────────────────────────────────────
    if root_cause is None:
        root_cause = RootCause(
            explanation="Root cause not available.",
            fault_location="unknown:0",
            confidence=0.0,
        )
    if fix_plan is None:
        fix_plan = FixPlan(
            steps=[],
            affected_files=[],
            rationale="Fix plan not available.",
        )
    language = (repo_analysis or {}).get("language", "python") if repo_analysis else "python"

    llm = get_llm_client()

    # ── Step 1: generate structured test case descriptions ────────────────
    case_prompt  = _build_test_case_prompt(bug_report, root_cause, fix_plan, code_diff or "")
    case_response = llm.invoke(case_prompt, max_tokens=1024, temperature=0.3)
    test_cases   = parse_test_cases_from_text(case_response)

    # ── Step 2: generate runnable pytest source ───────────────────────────
    if test_cases:
        pytest_prompt    = _build_pytest_prompt(test_cases, root_cause, fix_plan, language)
        pytest_response  = llm.invoke(pytest_prompt, max_tokens=2048, temperature=0.1)
        pytest_source    = _extract_pytest_source(pytest_response)
    else:
        pytest_source = ""

    # Fall back to a stub if LLM produced no parseable code
    if not pytest_source.strip():
        pytest_source = _make_stub_pytest(test_cases, bug_report)

    # ── Validate the generated source (syntax only — no execution) ───────
    suite = TestSuite(cases=test_cases, raw_source=pytest_source)
    validation = validate_test_suite(suite)
    errors = list(state.get("errors") or [])
    errors.extend(validation.issues)   # surface issues as pipeline errors

    # ── test_results: NOT EXECUTED sentinel ──────────────────────────────
    # We NEVER claim tests passed or failed here — that requires actual
    # execution by an authorised step outside this node.
    not_executed: TestResults = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "output": _NOT_EXECUTED_OUTPUT,
    }

    return {
        "generated_tests": pytest_source,
        "test_results":    not_executed,
        "current_stage":   "verification",
        "errors":          errors,
    }
