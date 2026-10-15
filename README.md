# Orbit AI — Flowspace Support Assistant

Orbit is a retrieval-augmented generation (RAG) support chatbot for **Flowspace**, a fictional project-management SaaS product. Signed-in users ask support questions in natural language. Orbit answers **only** from Flowspace's own support documents and shows which documents each answer came from.

## The problem it solves

General-purpose chatbots answer confidently even when they don't know the answer. A support assistant can't do that: an invented refund policy or price is worse than no answer. Orbit addresses this by:

- **Grounding answers in the docs.** It retrieves the most relevant passages from the support docs and tells the model to answer only from them.
- **Using a fixed fallback.** When the docs don't cover a question, it replies with one fixed message pointing the user to human support instead of guessing.
- **Showing sources.** The doc files used for each answer are shown, so users can tell where an answer came from.

## Features

- **Grounded answers.** Questions are embedded with Gemini and matched against the doc chunks in Chroma Cloud. Only chunks within a distance threshold are passed to the model.
- **Source attribution.** Each answer lists the doc files it used. Fallback answers show no sources.
- **Strict system prompt.** It allows only grounded answers, treats retrieved text as data rather than instructions, tells the model to refuse prompt-injection attempts, and uses one fixed fallback sentence for unknown or off-topic questions.
- **Accounts.** Signup and login with bcrypt-hashed passwords stored in Neon PostgreSQL, and JWT bearer tokens valid for 7 days.
- **Server-side validation.** Emails are normalised and passwords and questions have length limits (details under [Authentication and validation](#authentication-and-validation)).
- **Graceful upstream failures.** If Gemini or Chroma is unavailable, `/chat` returns `503` with a JSON message instead of crashing.
- **Automatic index sync.** On startup the backend checks whether the docs have changed since the last index and re-indexes only when needed.
- **Frontend error handling.** Users see readable messages for validation, outage and network errors, and an expired session sends them back to the login page.
- **Offline test suites.** 170 backend tests (pytest) and 26 frontend tests (Node's built-in test runner) that never touch live services.

## Architecture

```
┌──────────────────────────┐   HTTPS + JSON   ┌───────────────────────────────────────────┐
│ React + Vite + Tailwind  │ ───────────────▶ │ FastAPI backend (backend/app/main.py)     │
│ (frontend/)              │   Bearer JWT     │                                           │
│                          │ ◀─────────────── │  /signup, /login ──▶ auth.py (bcrypt, JWT)│
│ Landing → Auth → Chat    │                  │        │                                  │
└──────────────────────────┘                  │        ▼                                  │
                                              │  SQLAlchemy ──▶ Neon PostgreSQL (users)   │
                                              │                                           │
                                              │  /chat ──▶ llm.py ──▶ rag.py              │
                                              │              │          ├─▶ Gemini embed  │
                                              │              │          └─▶ Chroma Cloud  │
                                              │              └─▶ Gemini LLM + prompt      │
                                              └───────────────────────────────────────────┘
```

### How a chat request flows

1. **Frontend.** `ChatPage.jsx` calls `askOrbit()` in `frontend/src/api.js`, which sends `POST /chat` with `Authorization: Bearer <token>`.
2. **Authentication.** `get_current_user` in `main.py` checks the bearer token. A missing, malformed or expired token returns `401`.
3. **Validation.** The question is trimmed and must be 1–1000 characters; otherwise the API returns `422`.
4. **Retrieval** (`rag.py`). The question is embedded with the Gemini embedding model, and Chroma returns the 3 nearest chunks. Chunks with a distance above `1.2` are discarded.
5. **No relevant chunks.** The fixed fallback message is returned with no sources. The language model is not called.
6. **Generation** (`llm.py`). The chunks are wrapped in `<context>` blocks and sent to Gemini with the system prompt from `prompts.py` at temperature 0.2.
7. **Response.** The result is `{ "answer": ..., "sources": [...] }`. Sources are the de-duplicated doc filenames. They are cleared when the model returns the fallback message, or nothing at all.
8. **Upstream errors.** Gemini or Chroma failures (API errors, network errors, timeouts) become `503` with a JSON message. Bugs in the application still produce a normal `500`, so they stay visible.

### How the index is built

The backend reads `backend/docs/*.md` and splits the text into 500-character chunks with a 50-character overlap. It embeds each chunk with Gemini and stores it in the Chroma Cloud collection `flowspace_docs`. Chunk IDs look like `pricing.md_0` and record their source file. See [Index synchronisation](#index-synchronisation) for when this happens.

## Repository structure

```
orbit-AI/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app: routes, request validation, startup (lifespan) index sync
│   │   ├── config.py        # Loads .env; required-variable checks; CORS_ORIGINS parsing
│   │   ├── auth.py          # bcrypt hashing, JWT create/decode (HS256, 7-day expiry)
│   │   ├── database.py      # SQLAlchemy engine (pool_pre_ping) and per-request sessions
│   │   ├── model.py         # User table
│   │   ├── rag.py           # Doc loading, chunking, embeddings, Chroma access, index sync
│   │   ├── llm.py           # Answer generation, fallback handling, upstream-error handling
│   │   ├── prompts.py       # System prompt
│   │   └── reindex.py       # Manual index sync command (python -m app.reindex)
│   ├── docs/                # The knowledge base: Flowspace support articles (Markdown)
│   ├── scripts/
│   │   └── live_smoke.py    # Manual end-to-end check against LIVE services (costs money)
│   ├── tests/               # Offline pytest suite (conftest.py blocks network and real .env)
│   ├── .env.example         # Template for backend/.env
│   ├── requirements.txt     # Pinned runtime dependencies
│   └── requirements-dev.txt # Runtime + test dependencies
└── frontend/
    ├── src/
    │   ├── App.jsx          # Page state (landing / auth / chat) and session handling
    │   ├── api.js           # signup / login / askOrbit calls
    │   ├── apiClient.js     # Safe response parsing and readable error messages
    │   ├── session.js       # Client-side JWT expiry check
    │   └── components/      # Landing, AuthPage, ChatPage, brand components
    ├── tests/               # Offline tests for apiClient.js and session.js
    └── package.json
```

## Prerequisites

- **Python 3.10 or newer.** The code uses `str | None` type syntax. The project is developed on Python 3.12.
- **Node.js 18 or newer** to run and build the frontend (Vite 5 needs it). `npm test` passes a glob pattern to Node's built-in test runner, which needs **Node 21 or newer**. The project is developed and tested only on Node 24.
- Accounts and credentials for:
  - **Google Gemini API**, for embeddings and generation.
  - **Chroma Cloud**: an API key, tenant and database.
  - **Neon**, or any PostgreSQL database, with a connection string.

## Local setup

### 1. Backend

```bash
cd backend
python -m venv venv

# Activate the virtual environment
source venv/bin/activate          # macOS / Linux
venv\Scripts\activate             # Windows (cmd / PowerShell)

pip install -r requirements.txt          # runtime only
# or
pip install -r requirements-dev.txt      # runtime + pytest, needed to run the tests
```

`requirements.txt` pins every direct dependency to an exact version. `requirements-dev.txt` includes it with `-r` and adds `pytest`.

Then create your environment file:

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Fill in `backend/.env` as described in [Environment variables](#environment-variables). Never commit this file; it is already listed in `.gitignore`.

### 2. Frontend

```bash
cd frontend
npm install
```

Optionally, create `frontend/.env` to point the frontend at a backend other than the default:

```
VITE_API_URL=http://localhost:8000
```

If `VITE_API_URL` is not set, the frontend calls `http://localhost:8000`.

## Environment variables

The backend reads these from `backend/.env`. `backend/.env.example` lists them all with placeholder values.

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | **Yes** | Google Gemini API key. The app refuses to start without it. |
| `LLM_MODEL` | Yes | Gemini model used to write answers. The example file sets one. |
| `EMBEDDING_MODEL` | Yes | Gemini embedding model used for docs and questions. The example file sets one. Changing it triggers a full re-index on the next sync. |
| `CHROMA_API_KEY` | Yes | Chroma Cloud API key. |
| `CHROMA_TENANT` | Yes | Chroma Cloud tenant ID. |
| `CHROMA_DATABASE` | Yes | Chroma Cloud database name. |
| `JWT_SECRET` | **Yes** | Secret for signing login tokens. Use a long random value. The app refuses to start without it. Changing it logs out every user. |
| `DATABASE_URL` | **Yes** | PostgreSQL connection string, e.g. `postgresql://user:password@host/dbname?sslmode=require`. The app refuses to start without it. |
| `CORS_ORIGINS` | No | Comma-separated list of frontend origins allowed to call the API. If unset, it defaults to `http://localhost:5173` and the project's Vercel URL. |

The three variables marked in bold are checked at startup and give a clear error if missing. The others aren't checked up front, so a missing value only shows up when that service is first used.

## Running the project

**Backend** (from `backend/`, with the virtual environment active):

```bash
uvicorn app.main:app --reload
```

The API runs on `http://localhost:8000`, and `GET /health` returns `{"status": "ok"}`.

**Startup contacts live services.** It runs the index sync, which may make paid Gemini embedding calls and write to your Chroma Cloud collection. See [Index synchronisation](#index-synchronisation).

**Frontend** (from `frontend/`):

```bash
npm run dev
```

Open `http://localhost:5173`. For a production build, run `npm run build`; the output goes to `frontend/dist/`.

### API endpoints

| Method | Path | Auth | Body | Success response |
|---|---|---|---|---|
| `GET` | `/health` | — | — | `{"status": "ok"}` |
| `POST` | `/signup` | — | `{"email", "password"}` | `{"token", "email"}` |
| `POST` | `/login` | — | `{"email", "password"}` | `{"token", "email"}` |
| `POST` | `/chat` | Bearer token | `{"question"}` | `{"answer", "sources": [...]}` |

## Testing

Both test suites are **offline**. They don't need API keys and never contact Gemini, Chroma Cloud, Neon or any other network service.

**Backend** (from `backend/`, after installing `requirements-dev.txt`):

```bash
python -m pytest -q -p no:cacheprovider
```

The test setup in `tests/conftest.py`:
- **Ignores your real configuration:** it never loads `backend/.env`, and sets dummy values for every config variable.
- **Uses a throwaway database:** an in-memory SQLite database.
- **Blocks live services:** creating a Chroma Cloud client raises an error, and any outbound network connection is blocked.
- **Fakes Gemini and Chroma:** both are replaced with fakes. One test uses a local in-memory Chroma client.

The `-p no:cacheprovider` flag stops pytest from creating a `.pytest_cache` folder.

The suite covers:
- authentication and input validation;
- CORS and configuration;
- answer generation, fallback handling and upstream-error handling;
- chunking;
- index sync, including failure and retry behaviour;
- startup behaviour.

**Frontend** (from `frontend/`):

```bash
npm test
```

This runs Node's built-in test runner on `frontend/tests/`. It covers response parsing (including non-JSON errors), the readable error messages, network failures, and the JWT expiry check. The React components themselves are not unit-tested.

**Live smoke test (manual, costs money).** `python -m scripts.live_smoke`, run from `backend/`, uses your real `.env`. It **forces a full re-index** and makes paid Gemini calls. It is intentionally kept outside the pytest suite. Only run it on purpose.

## Index synchronisation

The Chroma collection stores a **fingerprint**, a SHA-256 hash of:
- every doc's filename and text;
- the chunk size and overlap;
- the embedding model;
- an `INDEX_VERSION` constant.

On each startup the backend compares it with the current docs:

- **Unchanged** (fingerprint matches and the collection isn't empty): nothing happens. There are no embedding calls and no writes.
- **Changed, or no fingerprint stored yet:**
  1. Every chunk is re-embedded. If embedding fails, Chroma is left untouched.
  2. The new chunks are upserted.
  3. Chunks that no longer exist, from deleted or shortened docs, are removed.
  4. The new fingerprint is stored last.
- **If an upsert or delete fails partway,** the old fingerprint is kept, so the next sync retries. These steps are not atomic: until the retry succeeds, the collection can briefly hold new chunks alongside stale ones.
- **If Gemini or Chroma is unreachable at startup,** the error is logged and the app **starts anyway**, serving the existing index. In that state `/chat` may return `503` until the service recovers. A bug in the sync code still stops startup, so it is visible.

The first startup against a collection created before fingerprints existed re-indexes once. With the current docs that is about 15 paid embedding calls.

### Manual reindex

From `backend/`, with your real `.env`:

```bash
python -m app.reindex           # sync only if the docs changed
python -m app.reindex --force   # re-embed and rewrite everything
```

> **Warning:** both commands use your real credentials. When anything needs syncing, and always with `--force`, they make **paid Gemini embedding calls** and write to your Chroma Cloud collection.

> **Not yet verified against the real Chroma Cloud collection.** The sync is tested offline against fakes and a local in-memory Chroma client, using the same `chromadb` library version, but it has not been run against the remote collection. In particular, storing the fingerprint relies on the library's `modify(metadata=...)`, which replaces all collection metadata. The code carries existing keys over to account for this, but that has only been confirmed against the local client.

## Authentication and validation

- **Signup** (`POST /signup`):
  - **Email:** trimmed and lowercased before storing. It must contain exactly one `@` with text on both sides, contain no spaces, and be at most 254 characters.
  - **Password:** at least 8 characters and at most 72 bytes in UTF-8. bcrypt ignores anything beyond 72 bytes, so longer passwords are rejected instead of being silently truncated.
  - **Duplicate emails:** checked case-insensitively and rejected with `400 Email already registered`. That includes two signups racing each other, which the database's unique constraint catches.
- **Login** (`POST /login`):
  - **Lookup:** emails are matched case-insensitively, so accounts created before normalisation with mixed-case emails still work.
  - **No minimum length:** older accounts with shorter passwords can still log in. The 72-byte maximum still applies.
  - **One error message:** a wrong password and an unknown email both return the same `401` message. If two existing accounts differ only by email case, login is refused with that same message. Only the user IDs are logged, never the email.
- **Tokens:** HS256 JWTs signed with `JWT_SECRET`. They are valid for 7 days and are sent as `Authorization: Bearer <token>`. A missing, malformed or expired token returns `401`.
- **Chat:** questions are trimmed and must be 1–1000 characters.

### Error responses and what the frontend shows

| Situation | API response | Frontend shows |
|---|---|---|
| Invalid input | `422` with a list of errors (type, location and message only; submitted values are not echoed back) | The validation message, e.g. "Password must be at least 8 characters" |
| Wrong email or password | `401` | "Invalid email or password" |
| Expired or invalid token on `/chat` | `401` | Logs out and shows "Your session has expired. Please log in again." on the login page |
| Gemini or Chroma unavailable | `503` with JSON `detail` | "Orbit is temporarily unavailable. Please try again." |
| Other server error, including non-JSON bodies | `500`, `502`, etc. | "Orbit ran into a problem. Please try again." |
| Backend unreachable (offline, DNS, CORS) | — | "Can't reach Orbit right now. Check your connection and try again." |

The frontend also checks the stored token's expiry date on page load and won't restore a session that has clearly expired.

## Limitations

- **No conversation memory.** Every question is answered on its own.
- **Live behaviour is unverified:**
  - Whether the live model actually follows the system prompt hasn't been verified with the current prompt. The tests only check how the application handles the model's output.
  - The index sync hasn't been run against the remote Chroma Cloud collection (see above).
- **Refusals can show sources.** Refusals for prompt-injection or competitor questions are free text, so they may still list sources. Only the exact fallback message clears them.
- **The distance threshold (`1.2`) and chunk settings haven't been tuned.**
- **Character-based chunking** can split text mid-word.
- **The stale-chunk lookup isn't paged.** It fetches all chunk IDs in one call, which is fine for the current small doc set.
- **No rate limiting.** Anyone who signs up can make chat requests that cost Gemini usage.
- **Authentication limitations:**
  - Tokens are stored in `localStorage`, and there are no refresh tokens.
  - Login responds slightly faster for unknown emails than for wrong passwords.
- **No database migrations.** Missing tables are created with SQLAlchemy's `create_all` as soon as `app.main` is imported, so loading the backend connects to the database in `DATABASE_URL`. Schema changes to existing tables are not applied.
- **Dependency pinning covers direct dependencies only.** There is no lock file, so sub-dependencies may resolve to different versions on a fresh install.
- **Docker is not supported.** `backend/Dockerfile` is an empty placeholder.
- **Not production-ready.** The project is a portfolio project, and no deployment has been verified as part of this documentation.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `RuntimeError: GEMINI_API_KEY is not set` (or `JWT_SECRET` / `DATABASE_URL`) | `backend/.env` is missing or incomplete. Copy `.env.example` and fill in every value. |
| Backend startup hangs for a while | The index sync is embedding the docs (first run, or the docs changed). Watch the log for `Index synced: ...`. |
| Log shows `startup index sync failed ...` / `Starting anyway` | Gemini or Chroma was unreachable at startup. Check the API keys, tenant and database, and your network. The next restart or `python -m app.reindex` retries. |
| Chat shows "Orbit is temporarily unavailable" | `/chat` returned `503`: Gemini or Chroma failed. The backend log shows which stage failed and the error type. |
| Chat shows "Can't reach Orbit right now" | The backend isn't running, `VITE_API_URL` is wrong, or the frontend's origin isn't allowed. Add it to `CORS_ORIGINS`. |
| Sent back to the login page with "session has expired" | The token is older than 7 days, or `JWT_SECRET` changed. Log in again. |
| Can't log in with an older account | If two accounts differ only by email case, login is refused on purpose. Resolve the duplicate in the database. |
| Answers use outdated doc content | Restart the backend or run `python -m app.reindex`. Both sync only when the docs changed. |
| `ModuleNotFoundError: No module named 'app'` | Run backend commands from inside `backend/`. |
| `pytest: command not found` | Install `requirements-dev.txt`, or use `python -m pytest` inside the virtual environment. |
