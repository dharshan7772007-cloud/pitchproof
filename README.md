# 🔧 Pitchproof

> **AI-powered developer workflow assistant — IBM Bob 2.0 Hackathon**

Pitchproof transforms a confusing bug report into a fully verified, ready-to-review fix in one automated pipeline run.

```
Bug Report → Repository Analysis → Root Cause → Fix Plan → Code Fix → Tests → Verification Report
```

---

## ✨ What It Does

| Stage | Node | What Happens |
|-------|------|--------------|
| 1 | **Repo Analyzer** | Scans the repository, detects language, scores files by relevance to the bug report using Python AST analysis |
| 2 | **Root Cause** | IBM Granite LLM analyses relevant code snippets and identifies the fault location with a confidence score |
| 3 | **Fix Planner** | LLM produces a structured, step-by-step fix plan with affected files and rationale |
| 4 | **Code Fixer** | LLM generates a unified diff patch (dry-run only — never applied automatically) |
| 5 | **Test Generator** | LLM generates pytest test cases targeting the proposed fix |
| 6 | **Verifier** | Deterministic checks on patch structure, test syntax, path safety + LLM-written human summary |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Streamlit UI                       │
│              (frontend/app.py :8501)                 │
└────────────────────┬────────────────────────────────┘
                     │ httpx POST /api/analyze
┌────────────────────▼────────────────────────────────┐
│              FastAPI Backend                         │
│           (backend/main.py :8000)                    │
│  /health  /api/analyze  /api/verify                  │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│           LangGraph Agent Pipeline                   │
│              (agent/graph.py)                        │
│                                                      │
│  repo_analyzer → root_cause → fix_planner            │
│       → code_fixer → test_generator → verifier       │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│         IBM watsonx.ai  (Granite models)             │
│         OpenAI-compatible fallback                   │
│         StubLLMClient  (tests / no-creds)            │
└─────────────────────────────────────────────────────┘
```

**Key design principles:**
- **Never executes** repository code or applies patches automatically
- **Path traversal guarded** everywhere a filesystem path is accepted
- **LLM abstraction** (`agent/llm.py`) — swap providers without touching nodes
- **StubLLMClient** enables full test coverage without any real credentials
- **278 / 278 tests pass** on a clean checkout

---

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/<your-org>/pitchproof.git
cd pitchproof
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env — add WATSONX_API_KEY + WATSONX_PROJECT_ID
```

See [`.env.example`](.env.example) for all options.  
Works without credentials — falls back to `StubLLMClient` (deterministic responses, great for demos of the UI scaffolding).

### 3. Start the backend

```bash
uvicorn backend.main:app --reload --port 8000
```

### 4. Start the frontend (new terminal)

```bash
streamlit run frontend/app.py
```

Open **http://localhost:8501** in your browser.

### 5. Run the demo pipeline (CLI — no browser needed)

```bash
python scripts/demo.py
```

This runs the full 6-stage pipeline against the built-in `tests/fixtures/sample_repo/` fixture and prints a formatted report.

---

## 🧪 Running Tests

```bash
python -m pytest tests/ -v
```

Expected: **278 passed** (no real credentials needed — all LLM calls use `StubLLMClient`).

```bash
# Fast smoke check
python -m pytest tests/ -q
```

---

## 📁 Project Structure

```
pitchproof/
├── .env.example                 # Credential template — copy to .env
├── requirements.txt             # All Python dependencies
│
├── agent/
│   ├── state.py                 # PitchproofState TypedDict + sub-structs
│   ├── graph.py                 # LangGraph 6-node pipeline definition
│   ├── llm.py                   # WatsonxClient / OpenAIClient / StubLLMClient
│   ├── nodes/
│   │   ├── repo_analyzer.py     # Node 1: git_tools + ast_tools
│   │   ├── root_cause.py        # Node 2: LLM structured fault analysis
│   │   ├── fix_planner.py       # Node 3: LLM structured fix plan
│   │   ├── code_fixer.py        # Node 4: LLM unified diff patch
│   │   ├── test_generator.py    # Node 5: LLM pytest generation
│   │   └── verifier.py          # Node 6: deterministic checks + LLM summary
│   └── tools/
│       ├── git_tools.py         # Safe repo traversal, file discovery
│       ├── ast_tools.py         # Python AST parsing, relevance scoring
│       ├── patch_tools.py       # ProposedChange / PatchSet, path guard
│       └── test_tools.py        # TestCase / TestSuite, syntax validation
│
├── backend/
│   ├── main.py                  # FastAPI app factory, CORS, /health
│   ├── api/routes.py            # GET /api/health, POST /api/analyze, POST /api/verify
│   ├── models/schemas.py        # Pydantic request / response models
│   └── services/
│       └── pitchproof_service.py  # validate_repo_path(), run_analysis()
│
├── frontend/
│   └── app.py                   # Streamlit UI — dark IDE theme, 6 result panels
│
├── scripts/
│   └── demo.py                  # CLI demo — runs pipeline, prints report
│
└── tests/
    ├── test_agent_core.py        # 16 tests
    ├── test_repo_analysis.py     # 57 tests
    ├── test_code_fixing.py       # 60 tests
    ├── test_verifier.py          # 56 tests
    ├── test_backend.py           # 54 tests
    ├── test_frontend.py          # 35 tests
    └── fixtures/sample_repo/    # IndexError + SyntaxError fixture files
```

---

## ⚙️ Configuration

All configuration is via environment variables. Copy `.env.example` → `.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `WATSONX_API_KEY` | — | IBM Cloud API key |
| `WATSONX_PROJECT_ID` | — | watsonx.ai project ID |
| `WATSONX_URL` | `https://us-south.ml.cloud.ibm.com` | Regional endpoint |
| `WATSONX_MODEL_ID` | `ibm/granite-3-8b-instruct` | Model to use |
| `LLM_PROVIDER` | `auto` | `watsonx` / `openai` / `auto` |
| `OPENAI_API_KEY` | — | OpenAI fallback key |
| `OPENAI_BASE_URL` | — | Custom base URL (Ollama, LM Studio…) |
| `CORS_ORIGINS` | `http://localhost:8501` | Allowed frontend origins |
| `API_PORT` | `8000` | Backend port |

---

## 🤖 Supported LLM Models

Pitchproof is designed for **IBM Granite code models** but works with any OpenAI-compatible endpoint.

### IBM watsonx.ai (recommended)

| Model ID | Best For |
|----------|----------|
| `ibm/granite-3-8b-instruct` | Fast, accurate — best for demos |
| `ibm/granite-3-2b-instruct` | Fastest, lowest latency |
| `ibm/granite-34b-code-instruct` | Highest quality code reasoning |
| `ibm/granite-20b-code-instruct-v2` | Balanced code + language |

### OpenAI-compatible fallback

Set `OPENAI_API_KEY` (and optionally `OPENAI_BASE_URL` for local models like Ollama):

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL_ID=gpt-4o
```

---

## 🎬 Hackathon Demo Flow (2–3 min)

1. **Start backend + frontend** (two terminal commands)
2. **Paste this bug report** into the UI:
   ```
   IndexError: list index out of range
   File "utils.py", line 14, in get_first_element
     return items[0]
   The function crashes when called with an empty list.
   ```
3. **Set repo path** to the absolute path of `tests/fixtures/sample_repo/` in your checkout
4. **Click "Analyse Bug"** — watch all 6 stages complete
5. **Walk the judges through**:
   - Stage tracker (all green ticks)
   - Root cause card (fault location + confidence %)
   - Fix plan (numbered steps)
   - Proposed diff (syntax-highlighted)
   - Generated pytest (ready to run)
   - Verification report (confidence score + summary paragraph)

Or use the CLI demo for a no-browser walkthrough:

```bash
python scripts/demo.py
```

---

## 🔒 Security Notes

- **No code execution** — patches and tests are generated but never run automatically
- **Path traversal protection** — all filesystem paths are validated before use
- **No secrets in code** — all credentials via environment variables only
- **CORS locked** — only `CORS_ORIGINS` from `.env` are allowed

---

## 📄 License

MIT — see [LICENSE](LICENSE) if present, otherwise refer to the hackathon submission terms.

---

<p align="center">Built for the <strong>IBM Bob 2.0 Hackathon</strong> · Powered by IBM Granite on watsonx.ai</p>
