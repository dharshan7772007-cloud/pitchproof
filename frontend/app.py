"""
frontend/app.py
----------------
Pitchproof — Streamlit frontend.

Run with:
    streamlit run frontend/app.py

Reads PITCHPROOF_API_URL from the environment (default: http://localhost:8000).
Never hard-codes secrets.  Never executes code from backend results.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration  (unchanged — do not modify)
# ---------------------------------------------------------------------------

API_URL: str = os.environ.get("PITCHPROOF_API_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT: int = 120  # seconds — pipeline can take a while

PIPELINE_STAGES = [
    ("repo_analysis",   "REPO SCAN"),
    ("root_cause",      "ROOT CAUSE"),
    ("fix_plan",        "FIX PLAN"),
    ("code_fix",        "CODE FIX"),
    ("test_generation", "TEST GEN"),
    ("verification",    "VERIFY"),
]

STATUS_ICONS = {
    "success": "✅",
    "partial": "⚠️",
    "failed":  "❌",
    "pending": "⬜",
    "running": "🔄",
}

# ---------------------------------------------------------------------------
# Premium CSS — dark developer-tool theme
# ---------------------------------------------------------------------------

_CSS = """
<style>
/* ── Reset & page shell ─────────────────────────────────────────────────── */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"] {
    background-color: #0a0c10 !important;
    color: #dde3ee !important;
}
[data-testid="stMain"] {
    background-color: #0a0c10 !important;
}
[data-testid="stHeader"] {
    background: transparent !important;
}
[data-testid="stSidebar"] { background-color: #0d1018 !important; }

/* Hide Streamlit chrome */
#MainMenu { visibility: hidden !important; }
footer    { visibility: hidden !important; }
[data-testid="stToolbar"]   { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }

/* ── Global typography ───────────────────────────────────────────────────── */
*, *::before, *::after {
    box-sizing: border-box;
}
html { font-size: 15px; }
body {
    font-family: -apple-system, "Inter", "Segoe UI", system-ui, sans-serif;
    line-height: 1.6;
}
h1,h2,h3,h4,h5,h6,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
    color: #f0f4ff !important;
    letter-spacing: -0.02em;
    font-weight: 700;
}
p, li,
[data-testid="stMarkdownContainer"] p { color: #8c99b3 !important; }

/* ── Card / bordered container ───────────────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #111520 !important;
    border: 1px solid #1e2538 !important;
    border-radius: 12px !important;
    padding: 1.5rem 1.75rem !important;
}

/* ── Inputs — dark IDE style ─────────────────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    background-color: #0d1018 !important;
    border: 1px solid #1e2538 !important;
    border-radius: 8px !important;
    color: #dde3ee !important;
    font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", "Consolas", monospace !important;
    font-size: 0.875rem !important;
    line-height: 1.6 !important;
    padding: 0.65rem 0.9rem !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: #3b6eff !important;
    box-shadow: 0 0 0 2px rgba(59, 110, 255, 0.18) !important;
    outline: none !important;
}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder {
    color: #3a4560 !important;
}
[data-testid="stTextInput"] label,
[data-testid="stTextArea"] label {
    color: #5a6a8a !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
}

/* ── Primary / submit button ─────────────────────────────────────────────── */
[data-testid="stFormSubmitButton"] button,
[data-testid="stFormSubmitButton"] button:focus {
    background: linear-gradient(135deg, #2b59ff 0%, #5b3fff 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 700 !important;
    font-size: 0.92rem !important;
    letter-spacing: 0.08em !important;
    padding: 0.7rem 2rem !important;
    box-shadow: 0 4px 24px rgba(43, 89, 255, 0.28) !important;
    transition: opacity 0.15s ease, box-shadow 0.15s ease !important;
    text-transform: uppercase !important;
}
[data-testid="stFormSubmitButton"] button:hover {
    opacity: 0.9 !important;
    box-shadow: 0 6px 28px rgba(43, 89, 255, 0.38) !important;
}
[data-testid="stFormSubmitButton"] button:disabled {
    opacity: 0.4 !important;
}

/* ── Code / diff blocks ──────────────────────────────────────────────────── */
[data-testid="stCode"] pre,
[data-testid="stCode"] code,
pre, code {
    background-color: #080b10 !important;
    border: 1px solid #1e2538 !important;
    border-radius: 8px !important;
    font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", "Consolas", monospace !important;
    font-size: 0.815rem !important;
    line-height: 1.65 !important;
    color: #c0cce8 !important;
}

/* ── Metric (pipeline stages) ───────────────────────────────────────────── */
[data-testid="stMetricValue"] {
    font-size: 1.4rem !important;
    font-weight: 700 !important;
    color: #3b82f6 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.63rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    color: #3a4560 !important;
}

/* ── Expander ───────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: #0d1018 !important;
    border: 1px solid #1e2538 !important;
    border-radius: 8px !important;
}
[data-testid="stExpander"] summary {
    color: #5a6a8a !important;
    font-size: 0.85rem !important;
}

/* ── Alert / info boxes ─────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    border-left-width: 3px !important;
}

/* ── Divider ────────────────────────────────────────────────────────────── */
hr { border-color: #1a2030 !important; margin: 1.5rem 0 !important; }

/* ── Spinner ────────────────────────────────────────────────────────────── */
[data-testid="stSpinner"] svg { stroke: #3b6eff !important; }

/* ── Select / success state ─────────────────────────────────────────────── */
[data-testid="stSuccess"] {
    background: #071a0e !important;
    border-color: #166534 !important;
    color: #4ade80 !important;
}

/* ── Success message text ────────────────────────────────────────────────── */
[data-testid="stAlert"][data-baseweb="notification"] p { color: #4ade80 !important; }
</style>
"""


def _inject_css() -> None:
    """Inject the premium CSS into the page."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# API client helpers  (logic unchanged — visual error messages only)
# ---------------------------------------------------------------------------

def call_analyze(bug_report: str, repo_path: str) -> Dict[str, Any]:
    """
    POST /api/analyze.  Returns the parsed JSON response dict.
    Raises RuntimeError with a user-friendly message on any failure.
    Never executes anything from the response.
    """
    payload = {"bug_report": bug_report, "repo_url": repo_path, "branch": "main"}
    try:
        resp = httpx.post(
            f"{API_URL}/api/analyze",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.ConnectError:
        raise RuntimeError(
            f"Could not connect to the Pitchproof backend at {API_URL}. "
            "Is the server running? (`uvicorn backend.main:app --reload`)"
        )
    except httpx.TimeoutException:
        raise RuntimeError(
            "The analysis pipeline timed out. "
            "Try a smaller repository or a more specific bug description."
        )
    except httpx.RequestError as exc:
        raise RuntimeError(f"Network error: {exc}")

    if resp.status_code == 422:
        detail = _safe_detail(resp)
        raise RuntimeError(f"Invalid input: {detail}")
    if resp.status_code >= 500:
        raise RuntimeError(
            "The backend encountered an internal error. Check server logs."
        )
    if not resp.is_success:
        raise RuntimeError(f"Unexpected HTTP {resp.status_code}: {_safe_detail(resp)}")

    try:
        return resp.json()
    except Exception:
        raise RuntimeError("Received a malformed response from the backend.")


def check_backend_health() -> bool:
    """Return True if the backend /health endpoint is reachable."""
    try:
        resp = httpx.get(f"{API_URL}/health", timeout=5)
        return resp.is_success
    except Exception:
        return False


def _safe_detail(resp: httpx.Response) -> str:
    """Extract a safe detail string from an error response."""
    try:
        data = resp.json()
        if isinstance(data, dict):
            return str(data.get("detail", resp.text[:200]))
    except Exception:
        pass
    return resp.text[:200]


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _confidence_bar(score: Optional[float]) -> str:
    if score is None:
        return ""
    pct = int(score * 100)
    filled = int(score * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"`{bar}` {pct}%"


def _stage_badge(raw_status: str) -> str:
    """Return an HTML badge for a pipeline stage status."""
    colours = {
        "success": ("#22c55e", "#071a0e"),
        "partial": ("#f59e0b", "#1a1000"),
        "failed":  ("#ef4444", "#1a0606"),
        "pending": ("#3a4560", "#0d1018"),
        "running": ("#3b6eff", "#08112a"),
    }
    label_map = {
        "success": "PASS",
        "partial": "WARN",
        "failed":  "FAIL",
        "pending": "–",
        "running": "…",
    }
    fg, bg = colours.get(raw_status, ("#3a4560", "#0d1018"))
    label  = label_map.get(raw_status, raw_status.upper())
    return (
        f'<span style="background:{bg};color:{fg};border:1px solid {fg}44;'
        f'border-radius:4px;padding:2px 9px;font-size:0.7rem;'
        f'font-family:monospace;font-weight:700;letter-spacing:0.08em;">'
        f'{label}</span>'
    )


def _card_label(text: str) -> str:
    """Return HTML for a small uppercase section label."""
    return (
        f'<p style="font-size:0.68rem;font-weight:700;color:#3a4560;'
        f'text-transform:uppercase;letter-spacing:0.12em;margin:0 0 0.35rem;">'
        f'{text}</p>'
    )


def _section_title(icon: str, title: str, badge_html: str = "") -> str:
    """Return HTML for a card section heading."""
    badge = f'<span style="margin-left:0.6rem;">{badge_html}</span>' if badge_html else ""
    return (
        f'<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1.1rem;">'
        f'<span style="font-size:1.1rem;">{icon}</span>'
        f'<span style="font-size:1rem;font-weight:800;color:#e8eeff;'
        f'letter-spacing:0.04em;text-transform:uppercase;">{title}</span>'
        f'{badge}'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Pipeline stage renderer
# ---------------------------------------------------------------------------

def render_pipeline_stages(data: Dict[str, Any]) -> None:
    """Render the horizontal 6-stage pipeline tracker."""
    stages_data = {s.get("stage"): s.get("status") for s in data.get("stages", [])}

    # Status → visual config
    def _stage_cfg(status: str) -> tuple[str, str, str, str]:
        # returns (bg, border, label_color, icon_html)
        configs = {
            "success": ("#071a0e", "#22c55e", "#22c55e",
                        '<span style="color:#22c55e;font-size:1rem;">✓</span>'),
            "partial": ("#1a1000", "#f59e0b", "#f59e0b",
                        '<span style="color:#f59e0b;font-size:1rem;">⚠</span>'),
            "failed":  ("#1a0606", "#ef4444", "#ef4444",
                        '<span style="color:#ef4444;font-size:1rem;">✕</span>'),
            "running": ("#08112a", "#3b6eff", "#7da4ff",
                        '<span style="color:#3b6eff;font-size:0.85rem;">◉</span>'),
            "pending": ("#0d1018", "#1e2538", "#3a4560",
                        '<span style="color:#3a4560;font-size:0.9rem;">○</span>'),
        }
        return configs.get(status, configs["pending"])

    cols = st.columns(len(PIPELINE_STAGES))
    for i, (col, (key, label)) in enumerate(zip(cols, PIPELINE_STAGES)):
        raw    = stages_data.get(key, "pending")
        bg, border, lc, icon = _stage_cfg(raw)
        num    = f"{i+1:02d}"
        arrow  = "→" if i < len(PIPELINE_STAGES) - 1 else ""
        with col:
            st.markdown(
                f'<div style="background:{bg};border:1px solid {border};border-radius:10px;'
                f'padding:0.85rem 0.9rem;text-align:center;position:relative;">'
                f'<div style="font-size:0.6rem;font-weight:700;color:#3a4560;'
                f'letter-spacing:0.12em;margin-bottom:0.3rem;">{num}</div>'
                f'<div style="margin-bottom:0.25rem;">{icon}</div>'
                f'<div style="font-size:0.65rem;font-weight:700;color:{lc};'
                f'letter-spacing:0.1em;text-transform:uppercase;">{label}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Result card renderers
# ---------------------------------------------------------------------------

def render_root_cause(data: Dict[str, Any]) -> None:
    rc_summary = data.get("root_cause_summary") or ""
    conf: Optional[float] = None
    fault: str = ""
    explanation: str = rc_summary

    for stage in data.get("stages", []):
        if stage.get("stage") == "root_cause" and stage.get("output"):
            out = stage["output"]
            conf = out.get("confidence")
            fault = out.get("fault_location", "")
            if out.get("explanation"):
                explanation = out["explanation"]
            break

    with st.container(border=True):
        st.markdown(_section_title("🧠", "Root Cause"), unsafe_allow_html=True)

        if fault and fault not in ("unknown:0", "unknown"):
            # Parse "file.py:line" format
            parts = fault.split(":")
            fname = parts[0] if parts else fault
            lineno = parts[1] if len(parts) > 1 else ""
            loc_html = (
                f'<div style="background:#080b10;border:1px solid #1e2538;border-radius:8px;'
                f'padding:0.7rem 1rem;margin-bottom:1rem;display:inline-block;">'
                f'<span style="font-family:monospace;font-size:0.9rem;color:#7da4ff;">{fname}</span>'
                + (f'<span style="color:#3a4560;font-size:0.9rem;font-family:monospace;"> : </span>'
                   f'<span style="font-family:monospace;font-size:0.9rem;color:#e8eeff;">line {lineno}</span>'
                   if lineno else "")
                + f'</div>'
            )
            st.markdown(loc_html, unsafe_allow_html=True)

        if explanation:
            st.markdown(
                f'<p style="color:#8c99b3;font-size:0.9rem;line-height:1.65;margin-bottom:1rem;">'
                f'{explanation}</p>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<p style="color:#3a4560;font-size:0.875rem;">No root-cause data available.</p>',
                unsafe_allow_html=True,
            )

        if conf is not None:
            pct = int(conf * 100)
            filled = round(conf * 20)
            bar_w  = filled * 5  # percent width of filled bar
            bar_color = "#22c55e" if conf >= 0.7 else ("#f59e0b" if conf >= 0.4 else "#ef4444")
            st.markdown(
                f'{_card_label("Confidence")}'
                f'<div style="display:flex;align-items:center;gap:0.75rem;">'
                f'<div style="flex:1;height:5px;background:#1e2538;border-radius:3px;overflow:hidden;">'
                f'<div style="width:{bar_w}%;height:100%;background:{bar_color};border-radius:3px;"></div>'
                f'</div>'
                f'<span style="font-size:1.3rem;font-weight:800;color:{bar_color};'
                f'font-variant-numeric:tabular-nums;">{pct}%</span>'
                f'</div>',
                unsafe_allow_html=True,
            )


def render_fix_plan(data: Dict[str, Any]) -> None:
    fix_desc: str = data.get("fix_description") or ""
    steps: list = []
    affected_files: list = []

    for stage in data.get("stages", []):
        if stage.get("stage") == "fix_plan" and stage.get("output"):
            out = stage["output"]
            steps = out.get("steps", [])
            affected_files = out.get("affected_files", [])
            if not fix_desc and out.get("rationale"):
                fix_desc = out["rationale"]
            break

    with st.container(border=True):
        st.markdown(_section_title("🛠", "Fix Plan"), unsafe_allow_html=True)

        if fix_desc:
            st.markdown(
                f'<p style="color:#8c99b3;font-size:0.875rem;line-height:1.65;margin-bottom:1rem;">'
                f'{fix_desc}</p>',
                unsafe_allow_html=True,
            )

        if steps:
            steps_html = ""
            for i, step in enumerate(steps, 1):
                steps_html += (
                    f'<div style="display:flex;gap:0.75rem;align-items:flex-start;'
                    f'padding:0.55rem 0;border-bottom:1px solid #1a2030;">'
                    f'<span style="font-size:0.68rem;font-weight:800;color:#3b6eff;'
                    f'font-family:monospace;padding-top:0.1rem;min-width:1.5rem;'
                    f'letter-spacing:0.05em;">{i:02d}</span>'
                    f'<span style="font-size:0.875rem;color:#c0cce8;">{step}</span>'
                    f'</div>'
                )
            st.markdown(
                f'<div style="margin-bottom:0.75rem;">{steps_html}</div>',
                unsafe_allow_html=True,
            )

        if affected_files:
            files_chips = " ".join(
                f'<span style="background:#0d1018;border:1px solid #1e2538;border-radius:4px;'
                f'padding:2px 8px;font-family:monospace;font-size:0.75rem;color:#7da4ff;">{f}</span>'
                for f in affected_files
            )
            st.markdown(
                f'{_card_label("Affected Files")}'
                f'<div style="display:flex;flex-wrap:wrap;gap:0.4rem;">{files_chips}</div>',
                unsafe_allow_html=True,
            )

        if not steps and not fix_desc:
            st.markdown(
                '<p style="color:#3a4560;font-size:0.875rem;">No fix plan available.</p>',
                unsafe_allow_html=True,
            )


def render_patch(data: Dict[str, Any]) -> None:
    diff = data.get("code_diff") or ""

    with st.container(border=True):
        # Header row
        st.markdown(
            f'{_section_title("💻", "Proposed Patch", badge_html=_not_applied_badge())}'
            f'<p style="font-size:0.8rem;color:#5a6a8a;margin-top:-0.75rem;margin-bottom:1rem;">'
            f'Unified diff — review before applying</p>',
            unsafe_allow_html=True,
        )

        if diff.strip():
            st.code(diff, language="diff")
        else:
            st.markdown(
                '<p style="color:#3a4560;font-size:0.875rem;">No proposed patch available.</p>',
                unsafe_allow_html=True,
            )


def _not_applied_badge() -> str:
    return (
        '<span style="background:#1a1000;color:#f59e0b;border:1px solid #f59e0b44;'
        'border-radius:4px;padding:2px 9px;font-size:0.68rem;font-family:monospace;'
        'font-weight:700;letter-spacing:0.08em;">PROPOSED · NOT APPLIED</span>'
    )


def _not_executed_badge() -> str:
    return (
        '<span style="background:#1a1000;color:#f59e0b;border:1px solid #f59e0b44;'
        'border-radius:4px;padding:2px 9px;font-size:0.68rem;font-family:monospace;'
        'font-weight:700;letter-spacing:0.08em;">NOT EXECUTED</span>'
    )


def render_generated_tests(data: Dict[str, Any]) -> None:
    tests_src = data.get("generated_tests") or ""

    with st.container(border=True):
        st.markdown(
            f'{_section_title("🧪", "Generated Tests", badge_html=_not_executed_badge())}'
            f'<div style="background:#1a1000;border:1px solid #f59e0b33;border-left:3px solid #f59e0b;'
            f'border-radius:0 6px 6px 0;padding:0.55rem 1rem;margin:-0.5rem 0 1rem;">'
            f'<span style="color:#f59e0b;font-size:0.78rem;font-weight:700;">⚠ NOT EXECUTED</span>'
            f'<span style="color:#8c99b3;font-size:0.78rem;"> — generated but not run. '
            f'Execute the test file to verify the fix.</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if tests_src.strip():
            st.code(tests_src, language="python")
        else:
            st.markdown(
                '<p style="color:#3a4560;font-size:0.875rem;">No tests were generated.</p>',
                unsafe_allow_html=True,
            )


def render_verification(data: Dict[str, Any]) -> None:
    status = data.get("status", "partial")
    conf   = data.get("confidence_score")
    errs   = data.get("errors", [])

    status_cfg = {
        "success": ("#22c55e", "#071a0e", "✓ PASS"),
        "partial": ("#f59e0b", "#1a1000", "⚠ PARTIAL"),
        "failed":  ("#ef4444", "#1a0606", "✕ FAILED"),
    }
    fg, bg, label = status_cfg.get(status, ("#3a4560", "#0d1018", "UNKNOWN"))

    tr     = data.get("test_results") or {}
    output = tr.get("output", "")

    with st.container(border=True):
        st.markdown(_section_title("🛡", "Verification Report"), unsafe_allow_html=True)

        # Status + confidence row
        conf_html = ""
        if conf is not None:
            pct = int(conf * 100)
            bar_color = "#22c55e" if conf >= 0.7 else ("#f59e0b" if conf >= 0.4 else "#ef4444")
            conf_html = (
                f'<div style="flex:1;text-align:right;">'
                f'<div style="font-size:0.65rem;font-weight:700;color:#3a4560;'
                f'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:0.2rem;">Confidence</div>'
                f'<div style="font-size:2rem;font-weight:800;color:{bar_color};'
                f'font-variant-numeric:tabular-nums;line-height:1;">{pct}%</div>'
                f'</div>'
            )

        st.markdown(
            f'<div style="display:flex;align-items:center;gap:1rem;'
            f'background:{bg};border:1px solid {fg}33;border-radius:10px;'
            f'padding:1rem 1.25rem;margin-bottom:1.25rem;">'
            f'<div style="flex:1;">'
            f'<div style="font-size:0.65rem;font-weight:700;color:#3a4560;'
            f'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:0.2rem;">Status</div>'
            f'<div style="font-size:1.3rem;font-weight:800;color:{fg};">{label}</div>'
            f'</div>'
            f'{conf_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Test execution status
        if "[NOT EXECUTED]" in output:
            st.markdown(
                '<div style="background:#1a1000;border:1px solid #f59e0b33;'
                'border-left:3px solid #f59e0b;border-radius:0 6px 6px 0;'
                'padding:0.55rem 1rem;margin-bottom:1rem;">'
                '<span style="color:#f59e0b;font-size:0.78rem;font-weight:700;">○ NOT EXECUTED</span>'
                '<span style="color:#8c99b3;font-size:0.78rem;"> — tests generated but not run.</span>'
                '</div>',
                unsafe_allow_html=True,
            )
        elif tr.get("passed", 0) > 0 or tr.get("failed", 0) > 0:
            passed = tr.get("passed", 0)
            failed = tr.get("failed", 0)
            errors = tr.get("errors", 0)
            st.markdown(
                f'<div style="font-size:0.875rem;color:#8c99b3;margin-bottom:0.75rem;">'
                f'<span style="color:#22c55e;">✓ {passed} passed</span> · '
                f'<span style="color:#ef4444;">✕ {failed} failed</span> · '
                f'<span style="color:#f59e0b;">⚠ {errors} errors</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        if errs:
            with st.expander(f"⚠ {len(errs)} issue(s) detected"):
                for e in errs:
                    st.markdown(
                        f'<div style="display:flex;gap:0.5rem;padding:0.3rem 0;'
                        f'border-bottom:1px solid #1a2030;">'
                        f'<span style="color:#f59e0b;font-size:0.8rem;">▸</span>'
                        f'<span style="color:#8c99b3;font-size:0.8rem;">{e}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

def render_empty_state() -> None:
    """Polished waiting state shown before any analysis is run."""

    capabilities = [
        ("🗂", "REPO ANALYSIS",    "Scans source files and ranks relevance to the bug"),
        ("🧠", "ROOT CAUSE",       "LLM identifies the fault location and explains why"),
        ("🛠", "PATCH GENERATION", "Produces a unified diff ready for review"),
        ("🧪", "TEST GENERATION",  "Generates pytest cases targeting the fix"),
        ("🛡", "VERIFICATION",     "Deterministic structural checks + confidence score"),
    ]

    st.markdown(
        '<div style="text-align:center;padding:2.5rem 1rem 1.5rem;">'
        '<div style="font-size:0.72rem;font-weight:700;color:#3b6eff;'
        'letter-spacing:0.18em;text-transform:uppercase;margin-bottom:0.75rem;">'
        'READY TO INVESTIGATE</div>'
        '<div style="font-size:1.6rem;font-weight:800;color:#e8eeff;'
        'letter-spacing:-0.02em;margin-bottom:0.5rem;">Enter a bug report to begin.</div>'
        '<div style="font-size:0.9rem;color:#5a6a8a;max-width:500px;margin:0 auto 2rem;">'
        'Pitchproof will analyse your repository, trace the root cause, '
        'propose a fix, generate tests, and produce a verification report.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(len(capabilities))
    for col, (icon, title, desc) in zip(cols, capabilities):
        with col:
            st.markdown(
                f'<div style="background:#0d1018;border:1px solid #1e2538;border-radius:10px;'
                f'padding:1rem 0.85rem;text-align:center;height:100%;">'
                f'<div style="font-size:1.4rem;margin-bottom:0.4rem;">{icon}</div>'
                f'<div style="font-size:0.63rem;font-weight:700;color:#3b6eff;'
                f'letter-spacing:0.12em;text-transform:uppercase;margin-bottom:0.4rem;">'
                f'{title}</div>'
                f'<div style="font-size:0.75rem;color:#3a4560;line-height:1.5;">{desc}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Workflow strip
    st.markdown(
        '<div style="margin:2rem auto 0;max-width:680px;'
        'background:#0d1018;border:1px solid #1e2538;border-radius:12px;'
        'padding:1.25rem 2rem;">'
        '<div style="font-size:0.65rem;font-weight:700;color:#3a4560;'
        'letter-spacing:0.14em;text-transform:uppercase;text-align:center;'
        'margin-bottom:1rem;">PITCHPROOF WORKFLOW</div>'
        '<div style="display:flex;align-items:center;justify-content:center;'
        'gap:0.5rem;flex-wrap:wrap;">'
        + _flow_step("BUG REPORT")
        + _flow_arrow()
        + _flow_step("REPO SCAN")
        + _flow_arrow()
        + _flow_step("ROOT CAUSE")
        + _flow_arrow()
        + _flow_step("PROPOSED FIX")
        + _flow_arrow()
        + _flow_step("VERIFICATION")
        +
        '</div></div>',
        unsafe_allow_html=True,
    )


def _flow_step(label: str) -> str:
    return (
        f'<span style="background:#111520;border:1px solid #1e2538;border-radius:6px;'
        f'padding:4px 12px;font-size:0.68rem;font-weight:700;color:#5a6a8a;'
        f'letter-spacing:0.08em;white-space:nowrap;">{label}</span>'
    )


def _flow_arrow() -> str:
    return '<span style="color:#1e2538;font-size:0.8rem;">→</span>'


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Pitchproof",
        page_icon="🔧",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _inject_css()

    # ── Top nav / hero ───────────────────────────────────────────────────────
    healthy = check_backend_health()

    status_html = (
        '<span style="background:#071a0e;color:#22c55e;border:1px solid #22c55e33;'
        'border-radius:20px;padding:3px 14px;font-size:0.68rem;font-weight:700;'
        'letter-spacing:0.1em;font-family:monospace;">● SYSTEM ONLINE</span>'
        if healthy else
        '<span style="background:#1a0606;color:#ef4444;border:1px solid #ef444433;'
        'border-radius:20px;padding:3px 14px;font-size:0.68rem;font-weight:700;'
        'letter-spacing:0.1em;font-family:monospace;">● SYSTEM OFFLINE</span>'
    )

    left_col, right_col = st.columns([3, 1])
    with left_col:
        st.markdown(
            '<div style="padding:1.5rem 0 0.25rem;">'
            '<div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.15rem;">'
            '<span style="font-size:1.5rem;line-height:1;">🔧</span>'
            '<span style="font-size:1.5rem;font-weight:900;letter-spacing:0.06em;'
            'color:#e8eeff;">PITCHPROOF</span>'
            '</div>'
            '<div style="font-size:0.65rem;font-weight:700;color:#3a4560;'
            'letter-spacing:0.18em;text-transform:uppercase;margin-bottom:1.1rem;">'
            'AI SOFTWARE DEBUGGING AGENT</div>'
            '<h1 style="font-size:2rem;font-weight:800;color:#e8eeff;'
            'letter-spacing:-0.03em;line-height:1.2;margin:0 0 0.5rem;">'
            'Turn a confusing bug report<br>into a verified fix.</h1>'
            '<p style="font-size:0.9rem;color:#5a6a8a;max-width:560px;margin:0;">'
            'Analyse your repository · identify the root cause · generate a proposed patch '
            '· create tests · verify the result.'
            '</p></div>',
            unsafe_allow_html=True,
        )
    with right_col:
        st.markdown(
            f'<div style="padding:1.5rem 0 0;text-align:right;">{status_html}</div>',
            unsafe_allow_html=True,
        )

    # Offline banner
    if not healthy:
        st.markdown(
            f'<div style="background:#1a0606;border:1px solid #ef444433;border-left:3px solid #ef4444;'
            f'border-radius:0 8px 8px 0;padding:0.75rem 1.25rem;margin:0.5rem 0 1rem;">'
            f'<span style="color:#ef4444;font-weight:700;font-size:0.85rem;">Backend unreachable</span>'
            f'<span style="color:#8c99b3;font-size:0.85rem;"> — cannot connect to '
            f'<code style="background:transparent;border:none;color:#7da4ff;">{API_URL}</code>. '
            f'Run <code style="background:transparent;border:none;color:#7da4ff;">'
            f'uvicorn backend.main:app --reload</code> and refresh.</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.stop()

    st.markdown('<div style="height:0.5rem;"></div>', unsafe_allow_html=True)
    st.divider()

    # ── Bug Console ──────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(
            '<div style="margin-bottom:1rem;">'
            '<div style="font-size:0.68rem;font-weight:700;color:#3b6eff;'
            'letter-spacing:0.18em;text-transform:uppercase;margin-bottom:0.25rem;">'
            '🐛 WHAT\'S BROKEN?</div>'
            '<div style="font-size:0.8rem;color:#5a6a8a;">'
            'Describe the bug and point Pitchproof at the repository.</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        with st.form("analyze_form"):
            bug_report = st.text_area(
                "BUG DESCRIPTION",
                placeholder=(
                    "Paste the full error message, traceback, or bug description here.\n\n"
                    "Example:\n"
                    "IndexError: list index out of range\n"
                    "  File \"utils.py\", line 11, in get_items\n"
                    "    return items[index]"
                ),
                height=160,
            )

            default_repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "sample_repo"))

            repo_path = st.text_input(
                "REPOSITORY PATH",
                value=default_repo,
                placeholder="/path/to/your/local/repository",
                help="Defaults to the bundled Pitchproof demo repository.",
            )

            context = st.text_area(
                "ADDITIONAL CONTEXT  (optional)",
                placeholder="Steps to reproduce · stack traces · related PRs · environment details…",
                height=80,
            )

            submitted = st.form_submit_button(
                "⚡  ANALYZE BUG",
                use_container_width=True,
            )

    # ── Validation + run ─────────────────────────────────────────────────────
    if submitted:
        if not bug_report.strip():
            st.markdown(
                '<div style="background:#1a0606;border:1px solid #ef444433;'
                'border-left:3px solid #ef4444;border-radius:0 8px 8px 0;'
                'padding:0.65rem 1rem;margin:0.5rem 0;">'
                '<span style="color:#ef4444;font-weight:700;">Required</span>'
                '<span style="color:#8c99b3;"> — please enter a bug description.</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.stop()
        if not repo_path.strip():
            st.markdown(
                '<div style="background:#1a0606;border:1px solid #ef444433;'
                'border-left:3px solid #ef4444;border-radius:0 8px 8px 0;'
                'padding:0.65rem 1rem;margin:0.5rem 0;">'
                '<span style="color:#ef4444;font-weight:700;">Required</span>'
                '<span style="color:#8c99b3;"> — please enter a repository path.</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.stop()

        full_report = bug_report.strip()
        if context.strip():
            full_report = f"{full_report}\n\nAdditional context:\n{context.strip()}"

        with st.spinner("Running Pitchproof analysis pipeline…"):
            try:
                data = call_analyze(full_report, repo_path.strip())
            except RuntimeError as exc:
                st.markdown(
                    f'<div style="background:#1a0606;border:1px solid #ef444433;'
                    f'border-left:3px solid #ef4444;border-radius:0 8px 8px 0;'
                    f'padding:0.75rem 1.25rem;margin:0.5rem 0;">'
                    f'<span style="color:#ef4444;font-weight:700;">Analysis failed</span>'
                    f'<span style="color:#8c99b3;"> — {exc}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.stop()

        # Success banner
        st.markdown(
            '<div style="background:#071a0e;border:1px solid #22c55e33;'
            'border-left:3px solid #22c55e;border-radius:0 8px 8px 0;'
            'padding:0.65rem 1.25rem;margin:0.75rem 0;">'
            '<span style="color:#22c55e;font-weight:700;">✓ Analysis complete</span>'
            '<span style="color:#8c99b3;"> — pipeline finished. Review results below.</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        st.divider()

        # ── Pipeline tracker ─────────────────────────────────────────────────
        st.markdown(
            '<div style="font-size:0.65rem;font-weight:700;color:#3a4560;'
            'letter-spacing:0.14em;text-transform:uppercase;margin-bottom:0.75rem;">'
            'DEBUGGING PIPELINE</div>',
            unsafe_allow_html=True,
        )
        render_pipeline_stages(data)

        st.divider()

        # ── Root Cause + Fix Plan (2-col) ────────────────────────────────────
        col_left, col_right = st.columns(2, gap="medium")
        with col_left:
            render_root_cause(data)
        with col_right:
            render_fix_plan(data)

        st.divider()

        # ── Proposed Patch ───────────────────────────────────────────────────
        render_patch(data)

        st.divider()

        # ── Generated Tests ──────────────────────────────────────────────────
        render_generated_tests(data)

        st.divider()

        # ── Verification Report ──────────────────────────────────────────────
        render_verification(data)

        st.divider()

        # ── Compact footer ───────────────────────────────────────────────────
        st.markdown(
            '<div style="text-align:center;padding:1.5rem 0 0.5rem;">'
            '<span style="font-size:0.75rem;font-weight:800;color:#3a4560;'
            'letter-spacing:0.12em;text-transform:uppercase;">PITCHPROOF</span>'
            '<span style="color:#1e2538;margin:0 0.5rem;">·</span>'
            '<span style="font-size:0.75rem;color:#3a4560;">'
            'AI Software Debugging &amp; Fix Agent</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    else:
        # ── Empty / pre-analysis state ───────────────────────────────────────
        st.divider()
        render_empty_state()

        st.divider()
        st.markdown(
            '<div style="text-align:center;padding:1rem 0 0.5rem;">'
            '<span style="font-size:0.75rem;font-weight:800;color:#3a4560;'
            'letter-spacing:0.12em;text-transform:uppercase;">PITCHPROOF</span>'
            '<span style="color:#1e2538;margin:0 0.5rem;">·</span>'
            '<span style="font-size:0.75rem;color:#3a4560;">'
            'AI Software Debugging &amp; Fix Agent</span>'
            '</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
