# Orbit AI

A RAG-powered customer support chatbot built for a fictional SaaS product called Flowspace. It answers user questions strictly from a set of support documents, refuses to answer anything outside that knowledge base, and sits behind its own authentication system so only signed-up users can query it.

Live app: https://orbit-ai-flowspace.vercel.app
Backend: https://orbit-ai-mjug.onrender.com

The backend is on Render's free tier, so it sleeps after ~15 minutes of no traffic. First request after that can take up to a minute while it wakes back up. Not a bug, just how free hosting works.

## Features

- Retrieval-Augmented Generation pipeline: support documents are chunked, embedded, stored, and retrieved by similarity before any answer is generated
- Distance-threshold relevance gate that skips the LLM call entirely and returns a fixed fallback message when no retrieved chunk is actually relevant
- Guardrailed system prompt hardened against prompt injection (including roleplay-framed attempts), competitor-comparison questions, and context leakage
- Source citations returned alongside every grounded answer
- JWT-based signup/login protecting the chat endpoint from unauthenticated use
- Full split-service deployment: FastAPI backend on Render, React frontend on Vercel

## Tech Stack

- Python / FastAPI
- SQLAlchemy
- PostgreSQL (hosted on Neon)
- Google Gemini API (embeddings + generation)
- ChromaDB Cloud (vector store)
- JWT (python-jose) + bcrypt/passlib (auth)
- React + Vite + Tailwind CSS

## How It Works

1. User signs up or logs in and receives a JWT.
2. User asks a question in the chat UI, sending the token with the request.
3. The backend embeds the question and queries ChromaDB Cloud for the most similar document chunks, filtering out anything above a set distance threshold.
4. If no chunk clears that threshold, the backend returns a fixed "I don't have that information" message with no sources — the LLM is never called.
5. Otherwise, the retrieved chunks are wrapped in context tags, combined with a guardrail system prompt, and sent to Gemini, which returns a grounded answer.
6. The answer is returned to the frontend along with the list of source documents actually used.

## Installation

```bash
git clone https://github.com/Guru2907/Orbit-AI.git
cd Orbit-AI/backend
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

Create a `.env` file in `backend/` with the required keys: `GEMINI_API_KEY`, `CHROMA_API_KEY`, `CHROMA_TENANT`, `CHROMA_DATABASE`, `DATABASE_URL`, `JWT_SECRET`.

```bash
cd ../frontend
npm install
```

## Usage

Backend:
```bash
uvicorn app.main:app --reload
```

Frontend:
```bash
npm run dev
```

## Project Structure

```
Orbit-AI/
├── backend/
│   ├── app/
│   │   ├── config.py
│   │   ├── rag.py
│   │   ├── prompts.py
│   │   ├── llm.py
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── model.py
│   │   └── auth.py
│   ├── docs/
│   │   └── *.md          # Flowspace support docs (knowledge base)
│   ├── tests/
│   │   └── test_chat.py
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api.js
│       ├── App.jsx
│       └── components/
└── README.md
```

## Key Implementation Details

- Implemented the RAG pipeline from scratch: overlapping text chunking, embedding via the Gemini Embeddings API, and storage/retrieval through ChromaDB Cloud using cosine distance.
- Used a distance threshold to gate the LLM call so the chatbot never generates an answer when nothing relevant was retrieved, instead returning a deterministic fallback message.
- Found and fixed a bug where the fallback answer could still list stale source citations; added a consistency check so sources are only returned when the answer actually came from the LLM using that context.
- Built authentication from scratch with SQLAlchemy models, bcrypt password hashing, and JWT tokens (7-day expiry), gating the metered `/chat` endpoint behind a valid token.
- Migrated the database from local SQLite to a hosted Neon Postgres instance after identifying that Render's free tier does not persist a local SQLite file across restarts.
- Hardened the system prompt iteratively against prompt injection (including roleplay/hypothetical framing) and competitor-comparison questions, verified through live testing on the deployed instance.

## What I Learned

- How a RAG pipeline actually works end-to-end — chunking, embedding, vector retrieval, relevance filtering, and grounded generation — by building each stage myself.
- How to design and iteratively harden a system prompt against real adversarial inputs, rather than assuming a single draft is safe.
- How JWT authentication and password hashing work under the hood by implementing them directly with SQLAlchemy, passlib, and python-jose instead of using a prebuilt auth service.
- Why an ephemeral filesystem (like Render's free tier) can silently lose a local database, and how to migrate to a persistent hosted database.
- How to structure and deploy a decoupled frontend/backend architecture, including environment-based CORS configuration across two separate hosting providers.

## Future Improvements

- Add automated tests (current test script is run manually, not wired into CI)
- Add per-user rate limiting on the `/chat` endpoint
- Expand the Flowspace knowledge base with additional support documents
- Add streaming responses for chat replies

## Author

Gurpreet Singh
