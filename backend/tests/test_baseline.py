"""
Baseline tests — lock in the CURRENT behaviour before any fixes, so later steps can
show exactly what changed. All offline: see conftest.py.
"""

import app.llm
import app.main
import app.rag
from app.auth import create_access_token, decode_access_token
from tests.conftest import CHROMA_CLIENT_CALLS, FakeCollection, run_isolated

CREDS = {"email": "user@example.com", "password": "secret123"}


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# --- health -------------------------------------------------------------------

def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


# --- signup / login -----------------------------------------------------------

def test_signup_returns_token_for_email(client):
    res = client.post("/signup", json=CREDS)
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == CREDS["email"]
    assert decode_access_token(body["token"]) == CREDS["email"]


def test_signup_duplicate_email_rejected(client):
    client.post("/signup", json=CREDS)
    res = client.post("/signup", json=CREDS)
    assert res.status_code == 400
    assert res.json()["detail"] == "Email already registered"


def test_login_after_signup(client):
    client.post("/signup", json=CREDS)
    res = client.post("/login", json=CREDS)
    assert res.status_code == 200
    assert decode_access_token(res.json()["token"]) == CREDS["email"]


def test_login_wrong_password(client):
    client.post("/signup", json=CREDS)
    res = client.post("/login", json={**CREDS, "password": "wrong-password"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"


def test_login_unknown_email(client):
    res = client.post("/login", json=CREDS)
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"


# --- chat auth ----------------------------------------------------------------

def test_chat_with_valid_token(client, fake_answer):
    token = create_access_token(email=CREDS["email"])
    res = client.post("/chat", json={"question": "What are the plans?"}, headers=auth_header(token))
    assert res.status_code == 200
    assert res.json() == {"answer": "Mocked answer", "sources": ["pricing.md"]}
    assert fake_answer == ["What are the plans?"]


def test_chat_with_invalid_token(client, fake_answer):
    res = client.post("/chat", json={"question": "hi"}, headers=auth_header("not-a-jwt"))
    assert res.status_code == 401
    assert fake_answer == []


def test_chat_with_non_bearer_header(client, fake_answer):
    res = client.post("/chat", json={"question": "hi"}, headers={"Authorization": "Token abc"})
    assert res.status_code == 401
    assert fake_answer == []


# --- startup indexing ---------------------------------------------------------

def test_startup_builds_index_when_collection_empty(client, monkeypatch):
    built = []
    # Step 5: startup now runs the real sync_index (against a fake collection / fake embedder).
    collection = FakeCollection()
    monkeypatch.setattr(app.main, "sync_index", app.rag.sync_index)
    monkeypatch.setattr(app.rag, "get_collection", lambda: collection)
    monkeypatch.setattr(app.rag, "embed_text", lambda text: built.append(text) or [0.0])
    app.main.startup_event()
    assert len(built) == len(collection.records) > 0


def test_startup_skips_build_when_collection_has_chunks(client, monkeypatch):
    # Step 5: "has chunks" now means "has chunks AND the stored fingerprint matches the docs".
    built = []
    fingerprint = app.rag.compute_index_fingerprint(app.rag.load_documents())
    collection = FakeCollection(
        records={"x_0": {}},
        metadata={app.rag.FINGERPRINT_KEY: fingerprint},
    )
    monkeypatch.setattr(app.main, "sync_index", app.rag.sync_index)
    monkeypatch.setattr(app.rag, "get_collection", lambda: collection)
    monkeypatch.setattr(app.rag, "embed_text", lambda text: built.append(text) or [0.0])
    app.main.startup_event()
    assert built == []
    assert collection.writes == []


# --- rag / llm helpers --------------------------------------------------------

def test_get_unique_sources_dedupes_preserving_order():
    chunks = [{"source": "b.md"}, {"source": "a.md"}, {"source": "b.md"}, {"source": "c.md"}]
    assert app.rag.get_unique_sources(chunks) == ["b.md", "a.md", "c.md"]


def test_build_context_and_prompt_format():
    # Step 7: source moved into the tag and the question got its own block (see test_prompt_injection.py).
    chunks = [{"source": "a.md", "text": "Alpha"}, {"source": "b.md", "text": "Beta"}]
    context = app.llm.build_context(chunks)
    assert context == (
        '<context source="a.md">\nAlpha\n</context>'
        "\n\n"
        '<context source="b.md">\nBeta\n</context>'
    )
    assert app.llm.build_prompt("Q?", context) == f"{context}\n\n<question>\nQ?\n</question>"


def test_generate_answer_without_chunks_skips_llm(monkeypatch):
    monkeypatch.setattr(app.llm, "retrieve_relevant_chunks", lambda question: [])

    def _fail(*args, **kwargs):
        raise AssertionError("LLM must not be called when no chunks are retrieved")

    monkeypatch.setattr(app.llm.client.models, "generate_content", _fail)
    result = app.llm.generate_answer("anything")
    assert result == {"answer": app.llm.NO_INFO_MESSAGE, "sources": []}


# --- Chroma import guard ------------------------------------------------------

def test_no_chroma_client_constructed_in_this_session(client):
    client.get("/health")
    assert CHROMA_CLIENT_CALLS == []


def test_fresh_import_does_not_construct_chroma_client():
    """Import app.main in a brand-new interpreter and count CloudClient constructions."""
    result = run_isolated(
        "import app.main\n"
        "assert 'app.rag' in __import__('sys').modules\n"
        "print('CLOUDCLIENT_CALLS=%d' % len(chroma_calls))\n"
    )
    assert result.returncode == 0, result.stderr
    assert "CLOUDCLIENT_CALLS=0" in result.stdout
