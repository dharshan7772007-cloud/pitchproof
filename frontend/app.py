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
# Configuration
# ---------------------------------------------------------------------------

API_URL: str = os.environ.get("PITCHPROOF_API_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT: int = 120  # seconds — pipeline can take a while

PIPELINE_STAGES = [
    ("repo_analysis",   "Repo Scan"),
    ("root_cause",      "Root Cause"),
    ("fix_plan",        "Fix Plan"),
    ("code_fix",        "Code Fix"),
    ("test_generation", "Test Generation"),
    ("verification",    "Verification"),
]

STATUS_ICONS = {
    "success": "✅",
    "partial": "⚠️",
    "failed":  "❌",
    "pending": "⬜",
    "running": "🔄",
}

# ---------------------------------------------------------------------------
# CSS — dark developer-tool theme
# ---------------------------------------------------------------------------

_CSS = """
<style>
/* ── Global ────────────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #0e1117 !important;
    color: #e2e8f0 !important;
}
[data-testid="stSidebar"] { background-color: #111827 !important; }

/* ── Typography ─────────────────────────────────────────────────────────── */
h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
    color: #f1f5f9 !important;
    letter-spacing: -0.01em;
}
p, li, label, [data-testid="stMarkdownContainer"] p { color: #cbd5e1 !important; }
.caption-text, [data-testid="stCaptionContainer"] { color: #64748b !important; }

/* ── Cards ──────────────────────────────────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #161b27 !important;
    border: 1px solid #1e293b !important;
    border-radius: 10px !important;
    padding: 1.25rem !important;
}

/* ── Inputs ─────────────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 6px !important;
    color: #e2e8f0 !important;
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace !important;
    font-size: 0.875rem !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.25) !important;
}

/* ── Analyze button ─────────────────────────────────────────────────────── */
[data-testid="stFormSubmitButton"] button {
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
    letter-spacing: 0.04em !important;
    padding: 0.65rem 2rem !important;
    transition: opacity 0.15s ease !important;
}
[data-testid="stFormSubmitButton"] button:hover { opacity: 0.88 !important; }

/* ── Metric (pipeline stages) ───────────────────────────────────────────── */
[data-testid="stMetricValue"] {
    font-size: 1.25rem !important;
    color: #a5b4fc !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.68rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    color: #64748b !important;
}

/* ── Code blocks (IDE style) ────────────────────────────────────────────── */
[data-testid="stCode"] pre,
[data-testid="stCode"] code {
    background-color: #0d1117 !important;
    border: 1px solid #21262d !important;
    border-radius: 8px !important;
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace !important;
    font-size: 0.82rem !important;
    line-height: 1.6 !important;
    color: #c9d1d9 !important;
}

/* ── Expander ───────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: #111827 !important;
    border: 1px solid #1e293b !important;
    border-radius: 8px !important;
}
[data-testid="stExpanderToggleIcon"] { color: #6366f1 !important; }

/* ── Alert / status boxes ───────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    border-left-width: 4px !important;
}

/* ── Divider ────────────────────────────────────────────────────────────── */
hr { border-color: #1e293b !important; margin: 1.25rem 0 !important; }

/* ── Spinner ────────────────────────────────────────────────────────────── */
[data-testid="stSpinner"] { color: #6366f1 !important; }

/* ── Hide Streamlit footer / menu ───────────────────────────────────────── */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
</style>
"""


def _inject_css() -> None:
    """Inject the dark-theme CSS into the page."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# API client helpers  (unchanged from Task 8)
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
# UI rendering helpers
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
        "success": ("#22c55e", "#052e16"),
        "partial": ("#f59e0b", "#1c1400"),
        "failed":  ("#ef4444", "#1c0707"),
        "pending": ("#475569", "#0f172a"),
        "running": ("#6366f1", "#1e1b4b"),
    }
    label_map = {
        "success": "PASS",
        "partial": "WARN",
        "failed":  "FAIL",
        "pending": "–",
        "running": "…",
    }
    fg, bg = colours.get(raw_status, ("#475569", "#0f172a"))
    label  = label_map.get(raw_status, raw_status.upper())
    return (
        f'<span style="background:{bg};color:{fg};border:1px solid {fg}33;'
        f'border-radius:4px;padding:1px 7px;font-size:0.72rem;'
        f'font-family:monospace;font-weight:700;letter-spacing:0.06em;">'
        f'{label}</span>'
    )


def render_pipeline_stages(data: Dict[str, Any]) -> None:
    """Render the horizontal pipeline stage row."""
    stages = {s.get("stage"): s.get("status") for s in data.get("stages", [])}
    cols = st.columns(len(PIPELINE_STAGES))
    for col, (key, label) in zip(cols, PIPELINE_STAGES):
        raw = stages.get(key, "pending")
        icon = STATUS_ICONS.get(raw, "⬜")
        col.metric(label=label, value=icon)


def render_root_cause(data: Dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown("#### 🧠 Root Cause")
        rc_summary = data.get("root_cause_summary") or ""
        if rc_summary:
            st.write(rc_summary)
        else:
            st.caption("No root-cause summary available.")
        for stage in data.get("stages", []):
            if stage.get("stage") == "root_cause" and stage.get("output"):
                out = stage["output"]
                conf = out.get("confidence")
                if conf is not None:
                    st.caption(f"Confidence: {_confidence_bar(conf)}")
                fault = out.get("fault_location", "")
                if fault and fault != "unknown:0":
                    st.caption(f"Fault location: `{fault}`")
                break


def render_fix_plan(data: Dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown("#### 🛠 Fix Plan")
        fix_desc = data.get("fix_description") or ""
        if fix_desc:
            st.write(fix_desc)
        for stage in data.get("stages", []):
            if stage.get("stage") == "fix_plan" and stage.get("output"):
                out = stage["output"]
                steps = out.get("steps", [])
                if steps:
                    st.markdown("**Steps:**")
                    for i, step in enumerate(steps, 1):
                        st.markdown(f"{i}. {step}")
                files = out.get("affected_files", [])
                if files:
                    st.markdown(f"**Files:** `{'`, `'.join(files)}`")
                break
        if not fix_desc:
            st.caption("No fix plan available.")


def render_patch(data: Dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown("#### 💻 Proposed Patch")
        st.markdown(
            '<span style="color:#f59e0b;font-size:0.8rem;font-weight:600;">'
            "⚠ PROPOSED ONLY — not applied automatically</span>",
            unsafe_allow_html=True,
        )
        diff = data.get("code_diff") or ""
        if diff.strip():
            st.code(diff, language="diff")
        else:
            st.caption("No proposed patch available.")


def render_generated_tests(data: Dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown("#### 🧪 Generated Tests")
        tests_src = data.get("generated_tests") or ""
        if tests_src.strip():
            st.markdown(
                '<span style="color:#f59e0b;font-size:0.8rem;font-weight:600;">'
                "⚠ GENERATED — not executed</span>",
                unsafe_allow_html=True,
            )
            st.code(tests_src, language="python")
        else:
            st.caption("No tests were generated.")


def render_verification(data: Dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown("#### 🛡 Verification Report")

        status = data.get("status", "partial")
        badge  = _stage_badge(status)
        st.markdown(f"**Status:** {badge}", unsafe_allow_html=True)

        conf = data.get("confidence_score")
        if conf is not None:
            st.markdown(f"**Confidence:** {_confidence_bar(conf)}")

        # Test execution notice
        tr     = data.get("test_results") or {}
        output = tr.get("output", "")
        if "[NOT EXECUTED]" in output:
            st.markdown(
                '<div style="background:#1c1400;border:1px solid #f59e0b33;'
                'border-left:3px solid #f59e0b;border-radius:6px;'
                'padding:0.6rem 1rem;margin:0.5rem 0;">'
                '<span style="color:#f59e0b;font-weight:700;">NOT EXECUTED</span> — '
                '<span style="color:#cbd5e1;font-size:0.875rem;">'
                "Tests were generated but not run. "
                "Execute the generated test file to verify the fix.</span></div>",
                unsafe_allow_html=True,
            )
        elif tr.get("passed", 0) > 0 or tr.get("failed", 0) > 0:
            passed = tr.get("passed", 0)
            failed = tr.get("failed", 0)
            errors = tr.get("errors", 0)
            st.markdown(
                f"**Test results:** ✅ {passed} passed · ❌ {failed} failed · ⚠️ {errors} errors"
            )

        errs = data.get("errors", [])
        if errs:
            with st.expander(f"⚠ {len(errs)} issue(s) / warning(s)"):
                for e in errs:
                    st.markdown(f"- {e}")


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

    # ── Header ────────────────────────────────────────────────────────────
    healthy = check_backend_health()

    st.markdown(
        """
        <div style="padding: 2rem 0 1rem;">
            <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.25rem;">
                <span style="font-size:2rem;">🔧</span>
                <span style="font-size:2rem;font-weight:800;letter-spacing:-0.02em;
                             background:linear-gradient(135deg,#a5b4fc,#818cf8);
                             -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
                    PITCHPROOF
                </span>
            </div>
            <p style="font-size:1.1rem;font-weight:600;color:#94a3b8;margin:0 0 0.25rem;">
                AI Software Debugging &amp; Fix Agent
            </p>
            <p style="font-size:0.875rem;color:#475569;margin:0;">
                Turn a confusing bug report into a verified fix.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Backend status pill
    if healthy:
        st.markdown(
            '<span style="background:#052e16;color:#22c55e;border:1px solid #22c55e44;'
            'border-radius:20px;padding:3px 12px;font-size:0.75rem;font-weight:700;'
            'letter-spacing:0.05em;">● BACKEND CONNECTED</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span style="background:#1c0707;color:#ef4444;border:1px solid #ef444444;'
            'border-radius:20px;padding:3px 12px;font-size:0.75rem;font-weight:700;'
            'letter-spacing:0.05em;">● BACKEND OFFLINE</span>',
            unsafe_allow_html=True,
        )
        st.error(
            f"Cannot reach the backend at `{API_URL}`. "
            "Run `uvicorn backend.main:app --reload` and refresh."
        )
        st.stop()

    st.markdown("<div style='margin:1.5rem 0 0.5rem;'>", unsafe_allow_html=True)
    st.divider()

    # ── Input card ────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(
            '<p style="font-size:1rem;font-weight:700;color:#a5b4fc;'
            'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.75rem;">'
            "🐛 What's Broken?</p>",
            unsafe_allow_html=True,
        )
        with st.form("analyze_form"):
            bug_report = st.text_area(
                "Bug description",
                placeholder=(
                    "Paste the full error message or bug description here.\n"
                    "Example: IndexError: list index out of range in utils.py at line 42"
                ),
                height=140,
            )
            repo_path = st.text_input(
                "Repository path",
                placeholder="/path/to/your/local/repository",
                help="Local filesystem path to the repository directory to analyse.",
            )
            context = st.text_area(
                "Additional context (optional)",
                placeholder="Steps to reproduce, stack traces, related PRs, environment details…",
                height=80,
            )
            submitted = st.form_submit_button(
                "⚡ ANALYZE BUG", use_container_width=True
            )

    # ── Validation + run ──────────────────────────────────────────────────
    if submitted:
        if not bug_report.strip():
            st.error("Please enter a bug description.")
            st.stop()
        if not repo_path.strip():
            st.error("Please enter a repository path.")
            st.stop()

        full_report = bug_report.strip()
        if context.strip():
            full_report = f"{full_report}\n\nAdditional context:\n{context.strip()}"

        with st.spinner("Running Pitchproof analysis pipeline…"):
            try:
                data = call_analyze(full_report, repo_path.strip())
            except RuntimeError as exc:
                st.error(str(exc))
                st.stop()

        st.success("Analysis complete.")
        st.divider()

        # ── Pipeline overview ─────────────────────────────────────────────
        st.markdown(
            '<p style="font-size:0.85rem;font-weight:700;color:#64748b;'
            'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.5rem;">'
            "Pipeline</p>",
            unsafe_allow_html=True,
        )
        render_pipeline_stages(data)
        st.divider()

        # ── Results (2-column layout for root cause + fix plan) ───────────
        col_left, col_right = st.columns(2, gap="medium")
        with col_left:
            render_root_cause(data)
        with col_right:
            render_fix_plan(data)

        st.divider()
        render_patch(data)
        st.divider()
        render_generated_tests(data)
        st.divider()
        render_verification(data)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
