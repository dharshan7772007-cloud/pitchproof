#!/usr/bin/env python3
"""
scripts/demo.py
----------------
Pitchproof CLI demo — runs the full 6-stage agent pipeline against the
built-in sample_repo fixture and prints a formatted report to the terminal.

Usage:
    python scripts/demo.py [--repo PATH] [--bug TEXT]

Defaults:
    --repo   tests/fixtures/sample_repo
    --bug    "IndexError: list index out of range in get_items() at utils.py:11
              The function crashes when called with an empty list."

No server needs to be running — the agent is invoked directly.
No credentials are required — falls back to StubLLMClient automatically.
"""
from __future__ import annotations

import argparse
import os
import sys
import textwrap
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Make sure the project root is on sys.path regardless of how the script is
# invoked (python scripts/demo.py from the project root, or from anywhere).
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed; env vars must be set manually


# ---------------------------------------------------------------------------
# ANSI colours (gracefully degraded on Windows without ANSI support)
# ---------------------------------------------------------------------------

def _supports_color() -> bool:
    return sys.stdout.isatty() and os.name != "nt" or os.environ.get("FORCE_COLOR")


_C = {
    "reset":  "\033[0m"  if _supports_color() else "",
    "bold":   "\033[1m"  if _supports_color() else "",
    "green":  "\033[92m" if _supports_color() else "",
    "yellow": "\033[93m" if _supports_color() else "",
    "cyan":   "\033[96m" if _supports_color() else "",
    "red":    "\033[91m" if _supports_color() else "",
    "dim":    "\033[2m"  if _supports_color() else "",
    "blue":   "\033[94m" if _supports_color() else "",
}


def _h1(text: str) -> str:
    return f"{_C['bold']}{_C['cyan']}{text}{_C['reset']}"

def _h2(text: str) -> str:
    return f"{_C['bold']}{text}{_C['reset']}"

def _ok(text: str) -> str:
    return f"{_C['green']}✔{_C['reset']} {text}"

def _warn(text: str) -> str:
    return f"{_C['yellow']}⚠{_C['reset']} {text}"

def _label(text: str) -> str:
    return f"{_C['dim']}{text}{_C['reset']}"

def _code(text: str) -> str:
    return f"{_C['blue']}{text}{_C['reset']}"

def _hr(width: int = 72) -> str:
    return _C['dim'] + "─" * width + _C['reset']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrap(text: str, indent: int = 4, width: int = 76) -> str:
    prefix = " " * indent
    return textwrap.fill(text, width=width, initial_indent=prefix, subsequent_indent=prefix)


def _section(title: str, content: str) -> None:
    print()
    print(_h2(f"  {title}"))
    print(_hr())
    print(content)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pitchproof CLI demo — runs the full agent pipeline and prints a report."
    )
    default_repo = str(_ROOT / "tests" / "fixtures" / "sample_repo")
    default_bug  = (
        "IndexError: list index out of range\n"
        "File \"utils.py\", line 11, in get_items\n"
        "    return items[index]\n"
        "The function crashes when called with an empty list."
    )
    parser.add_argument("--repo", default=default_repo, help="Local repo path to analyse")
    parser.add_argument("--bug",  default=default_bug,  help="Bug report text")
    args = parser.parse_args()

    repo_path = os.path.abspath(args.repo)
    bug_report = args.bug

    # ── Banner ──────────────────────────────────────────────────────────────
    print()
    print(_h1("  ╔══════════════════════════════════════════════════════════╗"))
    print(_h1("  ║              PITCHPROOF  —  CLI Demo                    ║"))
    print(_h1("  ║        AI Bug → Root Cause → Fix → Tests → Report       ║"))
    print(_h1("  ╚══════════════════════════════════════════════════════════╝"))
    print()
    print(_label("  Bug report:"))
    for line in bug_report.splitlines():
        print(f"    {line}")
    print()
    print(_label("  Repository:"), repo_path)
    print()

    # ── Import agent ────────────────────────────────────────────────────────
    try:
        from agent.graph import build_graph
    except ImportError as exc:
        print(f"\n  ERROR: Could not import agent.graph — {exc}")
        print("  Make sure you are running from the project root with the venv active.")
        sys.exit(1)

    # ── Run pipeline ─────────────────────────────────────────────────────────
    print(_h2("  Running pipeline …"))
    print(_hr())

    stages = [
        ("repo_analyzer",  "Repository Analysis"),
        ("root_cause",     "Root Cause Detection"),
        ("fix_planner",    "Fix Planning"),
        ("code_fixer",     "Code Fix Generation"),
        ("test_generator", "Test Generation"),
        ("verifier",       "Verification"),
    ]

    graph = build_graph()
    t0    = time.perf_counter()

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = graph.invoke({
            "bug_report":    bug_report,
            "repo_url":      repo_path,
            "current_stage": "repo_analysis",
            "errors":        [],
        })

    elapsed = time.perf_counter() - t0

    for _key, label in stages:
        print(_ok(f"  {label}"))

    print()
    print(_label(f"  Pipeline completed in {elapsed:.2f}s"))

    # ── Report ───────────────────────────────────────────────────────────────
    print()
    print(_h1("  ══ PIPELINE REPORT " + "═" * 52))

    # 1. Repo Analysis
    repo_analysis = result.get("repo_analysis") or {}
    _section("1 · Repository Analysis", "\n".join([
        _wrap(repo_analysis.get("summary", "(no summary)"), 4),
        "",
        _label("    Suspect files:"),
        *[f"      • {f}" for f in (repo_analysis.get("suspect_files") or ["(none)"])],
    ]))

    # 2. Root Cause
    root_cause = result.get("root_cause") or {}
    conf       = root_cause.get("confidence", 0.0)
    conf_pct   = f"{conf * 100:.0f}%"
    conf_color = _C['green'] if conf >= 0.7 else (_C['yellow'] if conf >= 0.4 else _C['red'])
    _section("2 · Root Cause", "\n".join([
        _wrap(root_cause.get("explanation", "(no explanation)"), 4),
        "",
        f"    {_label('Fault location:')} {_code(root_cause.get('fault_location', 'unknown'))}",
        f"    {_label('Confidence:')}     {conf_color}{conf_pct}{_C['reset']}",
    ]))

    # 3. Fix Plan
    fix_plan   = result.get("fix_plan") or {}
    steps      = fix_plan.get("steps") or []
    step_lines = [f"    {i+1}. {s}" for i, s in enumerate(steps)] or ["    (no steps)"]
    _section("3 · Fix Plan", "\n".join([
        _wrap(fix_plan.get("rationale", "(no rationale)"), 4),
        "",
        *step_lines,
    ]))

    # 4. Proposed Diff
    code_diff = (result.get("code_diff") or "").strip()
    diff_preview = code_diff[:600] + ("\n    … (truncated)" if len(code_diff) > 600 else "")
    _section("4 · Proposed Diff", _code(
        "\n".join(f"    {line}" for line in (diff_preview or "(none)").splitlines())
    ))

    # 5. Generated Tests
    gen_tests = (result.get("generated_tests") or "").strip()
    test_preview = gen_tests[:500] + ("\n    … (truncated)" if len(gen_tests) > 500 else "")
    _section("5 · Generated Tests", "\n".join(
        f"    {line}" for line in (test_preview or "(none)").splitlines()
    ))

    # 6. Verification Report
    vr     = result.get("verification_report") or {}
    status = vr.get("status", "unknown")
    score  = vr.get("confidence_score", 0.0)
    status_color = _C['green'] if status == "success" else (_C['yellow'] if status == "partial" else _C['red'])
    _section("6 · Verification Report", "\n".join([
        f"    {_label('Status:')}           {status_color}{status.upper()}{_C['reset']}",
        f"    {_label('Confidence score:')} {score * 100:.1f}%",
        "",
        _label("    Summary:"),
        _wrap(vr.get("bug_summary", "(no summary)"), 4),
        "",
        _label("    Fix description:"),
        _wrap(vr.get("fix_description", "(no description)"), 4),
    ]))

    print()
    print(_hr())
    print(_ok(f"  Demo complete — {elapsed:.2f}s  |  Status: {status.upper()}"))
    print()


if __name__ == "__main__":
    main()
