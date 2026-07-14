# Research Assistant

A full-stack, multi-agent research assistant. Ask a question — optionally with
a PDF attached — and a LangGraph-orchestrated pipeline plans the work, gathers
information from the PDF and/or the web, analyses it, and writes an answer. The
whole run is streamed to the browser over Server-Sent Events (SSE), so you see
each agent's progress live as a row of status pills.

- **Backend:** FastAPI + LangGraph, Gemini (LLM + embeddings), ChromaDB
  (vectors), PostgreSQL (task/document persistence), Serper.dev (web search).
- **Frontend:** React + Vite + TypeScript, a single-file ChatGPT-style UI with
  a live coordination trace.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Project layout](#project-layout)
3. [Prerequisites](#prerequisites)
4. [Getting the API keys](#getting-the-api-keys)
5. [Backend setup](#backend-setup)
6. [Frontend setup](#frontend-setup)
7. [Configuration reference](#configuration-reference)
8. [Using the app](#using-the-app)
9. [The SSE event protocol](#the-sse-event-protocol)
10. [Error handling & retries](#error-handling--retries)
11. [Troubleshooting](#troubleshooting)

---

## How it works

When you send a message, the backend creates a task and runs a **LangGraph**
state machine. Each node updates a shared `TaskState` and streams its status
back as it goes:

```
                 +-----------+
   your goal --> |  planner  |   decides needs_pdf / needs_web from the goal text
                 +-----+-----+
        +--------------+---------------+
        v              v               v
 +------------+ +------------+ +----------------+
 |gatherer_pdf| |gatherer_web| | gatherer_both  |  (PDF + web, concurrently)
 +-----+------+ +-----+------+ +--------+-------+
       +--------------+-----------------+
                      v
                +-----------+
                | analyser  |   compresses findings into insights
                +-----+-----+
                      v
                +-----------+
                |  writer   |   writes the final answer
                +-----+-----+
                      v
                  final answer
```

- The **planner** reasons over your question (not just "was a file attached")
  to decide which sources are needed. Both can be true at once — e.g. "compare
  my document with AWS's docs" runs the PDF and web gatherers concurrently.
- A **step budget** (`MAX_STEPS`) guards every node, so a run can never loop
  forever.
- If a node fails (after retries), the whole run **stops** — no partial
  answers — and the failing node is reported to the UI.

### PDF ingestion

If you attach a PDF, it's ingested inline before the graph runs: text is
extracted (PyMuPDF), split into overlapping chunks, embedded with Gemini, and
stored in Chroma. The document is also recorded in Postgres so you can re-use
it in later questions via its `doc_id` without re-uploading.

---

## Project layout

```
research_assistant_app/
|-- README.md
|-- backend/
|   |-- main.py                 # FastAPI app; /chat SSE endpoint; PDF ingestion
|   |-- config.py               # env vars, model names, tunables
|   |-- requirements.txt
|   |-- .env.example            # copy to .env and fill in
|   |-- db/
|   |   |-- schema.sql          # documents + tasks tables
|   |   |-- session.py          # psycopg async connection pool
|   |   +-- crud.py             # save_document / create_task / update_task / ...
|   |-- services/
|   |   |-- llm_client.py       # Gemini calls + structured errors + retry
|   |   |-- search_client.py    # Serper.dev web search
|   |   |-- vector_store.py     # Chroma add / query
|   |   +-- pdf_ingest.py       # PyMuPDF extract + chunking
|   |-- graph/
|   |   |-- state.py            # TaskState + trace helpers
|   |   |-- orchestrator.py     # builds & compiles the LangGraph
|   |   |-- planner.py          # planner node
|   |   |-- nodes_pdf.py        # PDF gatherer
|   |   |-- nodes_web.py        # web gatherer
|   |   |-- nodes_both.py       # concurrent PDF + web gatherer
|   |   |-- nodes_analyser.py   # analyser node
|   |   +-- nodes_writer.py     # writer node
|   +-- streaming/
|       +-- sse.py              # SSE formatting helpers (incl. structured error)
+-- frontend/
    |-- index.html              # loads Tailwind via CDN
    |-- package.json
    |-- tsconfig.json
    |-- vite.config.ts
    +-- src/
        |-- main.tsx
        +-- App.tsx             # the entire chat UI
```

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | Backend |
| Node.js | 18+ | Frontend (Vite 5) |
| PostgreSQL | 13+ | Task/document storage |
| Gemini API key | - | LLM + embeddings |
| Serper.dev API key | - | Web search (free, no card) |

---

## Getting the API keys

**Gemini** (`GEMINI_API_KEY`)
1. Go to Google AI Studio: https://aistudio.google.com/apikey
2. Create an API key and copy it.

**Serper.dev** (`SERPER_API_KEY`) — web search, free tier, no credit card
1. Sign up at https://serper.dev
2. Copy the API key from your dashboard.
3. The free allotment is **2,500 queries** (one-time). Each run uses ~1 search.

---

## Backend setup

All commands are run from the `backend/` folder.

### 1. Create a virtual environment and install dependencies

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Create the `.env` file

Copy the example and fill in your values:

```bash
# Windows:
copy .env.example .env
# macOS / Linux:
cp .env.example .env
```

Then edit `.env`:

```
GEMINI_API_KEY=your_actual_gemini_key
SERPER_API_KEY=your_actual_serper_key
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/research_agent
```

### 3. Create the database and tables

Create the database (adjust user/host as needed), then load the schema:

```bash
# create the database once
createdb research_agent        # or: psql -U postgres -c "CREATE DATABASE research_agent;"

# load the tables
psql "postgresql://postgres:postgres@localhost:5432/research_agent" -f db/schema.sql
```

The schema creates two tables: `documents` (ingested PDFs) and `tasks` (every
run, its status, final result, error, and full trace as JSONB).

### 4. Run the server

```bash
uvicorn main:app --reload --port 8000
```

If you hit a **reload loop** on Windows (uvicorn restarting endlessly because
it's watching the `uploads/` and `chroma_db/` folders it writes to), exclude
those from the watcher:

```bash
uvicorn main:app --reload --port 8000 --reload-exclude "uploads/*" --reload-exclude "chroma_db/*" --reload-exclude "*.pyc"
```

Verify it's up: open http://localhost:8000/health -> should return
`{"status":"ok"}`.

---

## Frontend setup

All commands are run from the `frontend/` folder.

```bash
cd frontend
npm install
npm run dev
```

Vite serves the app at **http://localhost:5173**. The frontend talks to the
backend at `http://localhost:8000` (set as `API_BASE` in `src/App.tsx`) and the
backend's CORS is configured to allow `http://localhost:5173`. If you change
either port, update both `API_BASE` and the `allow_origins` list in
`backend/main.py`.

Tailwind is loaded via CDN in `index.html`, so there's no Tailwind build step.

---

## Configuration reference

All settings live in `backend/config.py` (most are read from `.env`).

| Setting | Default | Meaning |
|---------|---------|---------|
| `GEMINI_API_KEY` | - | Gemini API key (from `.env`) |
| `SERPER_API_KEY` | - | Serper.dev key for web search (from `.env`) |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/research_agent` | Postgres connection string |
| `UPLOAD_DIR` | `uploads` | Where uploaded PDFs are stored |
| `CHROMA_DIR` | `./chroma_db` | Chroma persistence directory |
| `CHUNK_SIZE` | `1000` | PDF chunk size (characters) |
| `CHUNK_OVERLAP` | `200` | Overlap between chunks |
| `TOP_K` | `5` | Chunks retrieved per PDF query |
| `GEMINI_GEN_MODEL` | `gemini-3.5-flash` | Generation model |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` | Embedding model |
| `MAX_STEPS` | `5` | Step budget (planner + gatherer + analyser + writer = 4; 5 gives headroom) |
| `MAX_FINDINGS_CHARS` | `4000` | Caps how much gathered text enters the LLM context |


---

## Using the app

1. Start Postgres, the backend (`:8000`), and the frontend (`:5173`).
2. Open http://localhost:5173.
3. **Ask a question.** For web-only questions, just type and send.
4. **Attach a PDF** with the `+` button to ask about a document. Once ingested,
   the same document is reused for follow-up questions until you attach a new
   one or clear it.
5. Watch the pills: each agent shows `node . running` then `node . done` as it
   works. `Working...` stays pinned above the pills until the final answer or an
   error arrives.

---

## The SSE event protocol

The `/chat` endpoint streams `text/event-stream`. Each frame is
`event: <name>` + `data: <json>`. Event types:

| Event | When | Payload |
|-------|------|---------|
| `node_update` | A node starts (`running`), finishes (`done`), or fails (`failed`) | `{node, status, trace_tail}` |
| `doc_ingested` | A PDF finished ingesting | `{doc_id, filename}` |
| `task_started` | Task row created, graph about to run | `{task_id}` |
| `task_complete` | Run finished successfully | `{task_id, status, final_result, error}` |
| `error` | A node failed / the run stopped | `{type, status, title, message, node, retryable}` |

The frontend keys pills by `node` name and updates them **in place**, so each
node shows exactly one pill whose status changes over time. On an `error`
event, the failing node's pill flips to `error` and a clean message is shown in
the same bubble — no empty or duplicated bubbles.

---

## Error handling & retries

- **Structured errors, no leaks.** Every backend failure (LLM, web search, PDF,
  DB, unexpected exceptions) is normalised into a structured `error` SSE event
  with a user-safe `message`. Full stack traces are logged **server-side only**
  and never sent to the browser.
- **Retries.** Transient LLM errors (HTTP 408/429/500/502/503/504) are retried
  up to **3 times** with exponential backoff (~1s -> 10s) — enough to ride out a
  brief Gemini 503. Web search (Serper) retries the same way.
- **Fail fast on permanent errors.** Auth/permission/not-found (401/403/404)
  are not retried — retrying wouldn't help.
- **Retries are separate from the step budget.** A node retrying 3x still
  counts as one step.
- **No partial answers.** If any node ultimately fails, the run stops, the task
  is marked `failed` in Postgres, and the UI shows which node failed and why.

Example: if Gemini returns 503 during analysis, you'll see
`analyser . running` (through the retries), then `analyser . error`, then a
message like *"Issue with the analysis node — the model is currently
overloaded. Please try again in a few minutes."*

---

## Troubleshooting

**"Web search is currently unavailable."**
This is Serper failing. The real cause is logged server-side — look for a
`web search failed` traceback in the backend terminal just above this message.
Common causes: `SERPER_API_KEY` missing/typo'd in `.env`, the `.env` not being
loaded (it must sit in `backend/`), a network/firewall blocking
`google.serper.dev`, or an exhausted free quota. To see the raw error, you can
temporarily add `print("SERPER RAW ERROR:", repr(exc))` in the final `except`
block of `services/search_client.py`.

**"Requested model not found."**
`GEMINI_GEN_MODEL` in `config.py` isn't valid for your account. Switch it to a
model you have access to (e.g. `gemini-2.5-flash`).

**Empty or duplicated chat bubbles.**
This should not happen — the frontend handles the `error` event and keys pills
by node. If it does, confirm the frontend `App.tsx` is the current version and
that the backend is emitting `error` events (check the Network tab -> the
`/chat` response stream).

**uvicorn keeps reloading / `KeyboardInterrupt` in `logging/config.py`.**
That traceback is just uvicorn's `--reload` restarting a worker — it's
harmless. If it loops endlessly, the reloader is watching folders the app
writes to (`uploads/`, `chroma_db/`). Use the `--reload-exclude` flags shown in
the backend setup section, or run without `--reload`.

**CORS errors in the browser console.**
The backend allows `http://localhost:5173`. If your frontend runs on a
different port, add it to `allow_origins` in `backend/main.py`.

**Database connection errors on startup.**
Check `DATABASE_URL`, that Postgres is running, the database exists, and that
`db/schema.sql` has been loaded.

**"I/O operation on closed file" when uploading a PDF.**
Already handled — the upload is read into memory before streaming begins. If
you see it, make sure `backend/main.py` is the current version.
