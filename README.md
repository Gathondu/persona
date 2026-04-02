---
title: DNG
emoji: 🤖
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Persona

A full-stack LLM agent that responds in your voice with your expertise.  
**Backend:** FastAPI + SQLite (persistent chat history) + Cerebras (primary) + OpenRouter (fallback)  
**Frontend:** Svelte 5 (Runes) + Vite

---

## Monorepo layout

```
my-agent/
├── backend/          FastAPI app (main.py, agent.py, memory.py)
│   ├── llm_clients.py  # Cerebras + OpenRouter client factories
│   └── Dockerfile    Multi-stage build (frontend → backend)
├── frontend/         Svelte 5 SPA
├── docker-compose.yml
└── README.md
```

---

## Local development

### 1 — Prerequisites

| Tool | Version |
|------|---------|
| Python | ≥ 3.11 |
| uv | latest |
| Node.js | 20 LTS |

### 2 — Backend

```bash
cd backend
uv venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

uv sync
cp .env.example .env   # set CEREBRAS_* (primary) and OPENROUTER_* (fallback)
uv run uvicorn main:app --reload
```

### 3 — Frontend (separate terminal)

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/chat`, `/history`, `/health` to the FastAPI backend on port 8000.

### 4 — Docker (full stack)

Build the frontend and run everything in one container:

```bash
cd my-agent
docker build -f backend/Dockerfile -t my-agent .
docker run -p 7860:7860 --env-file backend/.env my-agent
```

Or use Compose (includes hot-reload backend + optional Vite dev server):

```bash
docker compose up                   # production-like
docker compose --profile dev up     # + Vite dev server on :5173
```

---

## Configuration

Create `backend/.env`:

```dotenv
CEREBRAS_API_KEY=...                           # primary; omit to use OpenRouter only
CEREBRAS_MODEL=gpt-oss-120b                    # optional override
OPENROUTER_API_KEY=sk-or-...                   # required fallback when Cerebras fails
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet   # optional override
APP_URL=https://your-hf-space-url              # optional, for HTTP-Referer header
```

---

## Personalising your AI double

Edit `backend/agent.py` and fill in the `SYSTEM_PROMPT`:

```python
SYSTEM_PROMPT = """
You are [Your Name]'s AI double. You respond exactly as [Your Name] would, 
using their tone, expertise in [domains], and writing style.
...
"""
```

---

## Deploying to Hugging Face Spaces

1. Create a new Space → **Docker** SDK, port **7860**.
2. Push the contents of `my-agent/` to the Space repo root  
   *(the `README.md` frontmatter above is already correct)*.
3. Add `CEREBRAS_API_KEY` (primary) and `OPENROUTER_API_KEY` (fallback) in **Settings → Repository secrets**.
4. HF Spaces will run `docker build -f Dockerfile .` from the root —  
   rename/copy `backend/Dockerfile` to the repo root, or add a root-level  
   `Dockerfile` that delegates to it.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat` | SSE stream. Body: `{ session_id, message }` |
| `GET` | `/history/{session_id}` | Full message history for a session |
| `GET` | `/health` | Liveness check |
