"""
agent/nodes/verifier.py
------------------------
Node 6 of 6 — Verification & Report Generation.

Performs deterministic structural validation of all previous pipeline outputs,
optionally uses the LLM to write a human-readable summary, and assembles the
final VerificationReport.

Verification checks (all deterministic — no LLM required):
  1. Proposed patch structural validity (diff format).
  2. Proposed patch path safety (no traversal, files inside repo).
  3. Generated test syntax validity (ast.parse — no execution).
  4. Test target file existence (optional — repo_url must be a local path).
  5. Root-cause confidence level.

LLM is used ONLY to produce a human-readable bug/fix summary paragraph.
Falls back cleanly with StubLLMClient.

CRITICAL INVARIANTS:
  - Never executes repository code.
  - Never applies patches.
  - Never claims tests passed unless they were actually executed.
  - test_results["output"] from test_generator carries the NOT_EXECUTED sentinel;
    the verifier preserves this and does not overwrite it with success claims.

Reads:   All previous node outputs
Writes:  state["verification_report"], state["current_stage"]
"""

from __future__ import annotations

from typing import List, Optional

from agent.llm import get_llm_client
from agent.state import (
    FixPlan, PitchproofState, RepoAnalysis, RootCause,
    TestResults, VerificationReport,
)
from agent.tools.test_tools import (
    TestSuite,
    check_test_targets_exist,
    parse_test_cases_from_text,
    validate_proposed_patch_structure,
    validate_test_suite,
    validate_test_syntax,
)


# Sentinel used by test_generator — verifier must not overwrite it with pass claims
_NOT_EXECUTED_SENTINEL = "[NOT EXECUTED]"


# ---------------------------------------------------------------------------
# LLM summary builder
# ---------------------------------------------------------------------------

def _build_summary_prompt(
    bug_report: str,
    root_cause: RootCause,
    fix_plan: FixPlan,
    code_diff: str,
) -> str:
    affected = ", ".join(fix_plan.get("affected_files") or []) or "unknown"
    return f"""You are a senior engineer writing a concise verification summary.

## Bug Report
{bug_report}

## Root Cause
{root_cause.get('explanation', 'unknown')}

## Fix Applied To
{affected}

## Proposed Diff (excerpt)
{(code_diff or '')[:400]}

## Task
Write two short paragraphs:
1. A plain-English description of the bug and why it occurred.
2. A plain-English description of the fix and what it changes.

Do NOT include section headers. Output the two paragraphs only.
"""


# ---------------------------------------------------------------------------
# Confidence scoring (deterministic)
# ---------------------------------------------------------------------------

def _compute_confidence(
    root_cause_conf: float,
    patch_valid: bool,
    tests_present: bool,
    issues: List[str],
) -> float:
    """
    Compute a deterministic aggregate confidence score in [0.0, 1.0].

    Weights:
      40% — root_cause confidence (from LLM)
      30% — patch is structurally valid
      20% — tests were generated
      10% — no blocking issues
    """
    score = root_cause_conf * 0.40
    score += 0.30 if patch_valid else 0.0
    score += 0.20 if tests_present else 0.0
    score += 0.10 if not issues else 0.0
    return round(min(score, 1.0), 3)


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def verifier(state: PitchproofState) -> dict:
    """
    Aggregate all pipeline results into a final VerificationReport.

    Reads:   All previous node outputs
    Writes:  state["verification_report"], state["current_stage"]
    """
    bug_report:      str                       = state.get("bug_report", "")
    repo_url:        str                       = state.get("repo_url", "")
    root_cause:      Optional[RootCause]      = state.get("root_cause")
    fix_plan:        Optional[FixPlan]         = state.get("fix_plan")
    code_diff:       Optional[str]             = state.get("code_diff", "")
    generated_tests: Optional[str]             = state.get("generated_tests", "")
    test_results:    Optional[TestResults]     = state.get("test_results")
    repo_analysis:   Optional[RepoAnalysis]    = state.get("repo_analysis")

    all_issues:   List[str] = list(state.get("errors") or [])
    all_warnings: List[str] = []

    # ── Apply safe defaults for missing upstream data ─────────────────────
    if root_cause is None:
        root_cause = RootCause(
            explanation="Root cause analysis not available.",
            fault_location="unknown:0",
            confidence=0.0,
        )
        all_warnings.append("root_cause was missing; confidence set to 0.")

    if fix_plan is None:
        fix_plan = FixPlan(steps=[], affected_files=[], rationale="")
        all_warnings.append("fix_plan was missing.")

    # ── 1. Validate proposed patch structure ──────────────────────────────
    patch_result = validate_proposed_patch_structure(code_diff or "")
    all_issues.extend(patch_result.issues)
    all_warnings.extend(patch_result.warnings)
    patch_valid = patch_result.valid and not patch_result.issues

    # ── 2. Validate generated test syntax ────────────────────────────────
    test_syntax_result = validate_test_syntax(generated_tests or "")
    all_issues.extend(test_syntax_result.issues)
    all_warnings.extend(test_syntax_result.warnings)

    # ── 3. Validate test suite structure ─────────────────────────────────
    test_cases = parse_test_cases_from_text(generated_tests or "")
    suite = TestSuite(cases=test_cases, raw_source=generated_tests or "")
    suite_result = validate_test_suite(suite)
    # Promote suite issues to warnings (they don't block a partial report)
    all_warnings.extend(suite_result.issues)

    tests_present = bool(generated_tests and generated_tests.strip())

    # ── 4. Check target files exist (only when repo_url is a local dir) ───
    import os
    if repo_url and os.path.isdir(repo_url) and test_cases:
        targets_result = check_test_targets_exist(suite, repo_url)
        all_warnings.extend(targets_result.issues)
        all_warnings.extend(targets_result.warnings)

    # ── 5. Guard: never claim tests passed unless actually executed ───────
    # Preserve the NOT_EXECUTED sentinel from test_generator.
    if test_results is None:
        test_results = TestResults(
            passed=0, failed=0, errors=0,
            output="[NOT EXECUTED] No test results available.",
        )
    elif _NOT_EXECUTED_SENTINEL in (test_results.get("output") or ""):
        # Keep the sentinel — do NOT overwrite with fake success counts
        pass   # test_results already correct
    # If a real execution result appears (future task), we accept it as-is.

    # ── 6. Determine overall status ───────────────────────────────────────
    if all_issues:
        status = "failed"
    elif all_warnings:
        status = "partial"
    else:
        status = "partial"   # "success" requires actual test execution

    # ── 7. Generate human-readable summary via LLM ───────────────────────
    try:
        summary_prompt = _build_summary_prompt(
            bug_report, root_cause, fix_plan, code_diff or ""
        )
        llm = get_llm_client()
        llm_summary = llm.invoke(summary_prompt, max_tokens=512, temperature=0.3)
    except Exception:
        llm_summary = ""

    # Split into bug_summary / fix_description (use paragraphs if possible)
    paragraphs = [p.strip() for p in llm_summary.split("\n\n") if p.strip()]
    bug_summary = paragraphs[0] if paragraphs else (
        f"Bug report: {bug_report[:200]}"
    )
    fix_description = paragraphs[1] if len(paragraphs) >= 2 else (
        fix_plan.get("rationale", "Fix description not available.")
    )

    # ── 8. Compute confidence ─────────────────────────────────────────────
    confidence = _compute_confidence(
        root_cause_conf=float(root_cause.get("confidence", 0.0)),
        patch_valid=patch_valid,
        tests_present=tests_present,
        issues=all_issues,
    )

    # ── Assemble report ───────────────────────────────────────────────────
    report: VerificationReport = {
        "bug_summary":        bug_summary,
        "root_cause_summary": root_cause.get("explanation", ""),
        "fix_description":    fix_description,
        "diff":               code_diff or "(no diff available)",
        "test_results":       test_results,
        "confidence_score":   confidence,
        "status":             status,
    }

    return {
        "verification_report": report,
        "current_stage":       "verification",
    }
