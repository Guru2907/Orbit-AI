"""
Step 4 — LLM/RAG robustness: empty model responses, upstream service failures (503),
fallback/source handling, prompt consistency, and the chunker tail fix.
All offline: Gemini and Chroma are replaced with fakes (see conftest.py).

Note: these tests prove how the APPLICATION handles model output. Whether the live model
actually follows the updated prompt rule 5 is NOT verified here (that needs a paid call).
"""

from types import SimpleNamespace

import httpx
import pytest
from chromadb.errors import InternalError as ChromaInternalError
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors

import app.llm
import app.main
import app.prompts
import app.rag
from app.auth import create_access_token
from app.llm import NO_INFO_MESSAGE, AnswerUnavailableError

QUESTION = "SECRET-QUESTION-MARKER how do refunds work?"
CHUNKS = [
    {"text": "Refunds within 14 days.", "source": "refund_policy.md", "distance": 0.3},
    {"text": "Cancel any time.", "source": "cancel_subscription.md", "distance": 0.5},
    {"text": "More refund details.", "source": "refund_policy.md", "distance": 0.7},
]
UNAVAILABLE = {"detail": "Orbit is temporarily unavailable. Please try again."}


def gemini_api_error(code=503):
    return genai_errors.ServerError(code, {"error": {"code": code, "message": "upstream detail", "status": "UNAVAILABLE"}})


@pytest.fixture
def fake_llm(monkeypatch):
    """Retrieval returns CHUNKS; generate_content returns whatever `state['text']` holds or raises `state['error']`."""
    state = {"text": "Refunds are available within 14 days.", "error": None, "calls": 0}

    monkeypatch.setattr(app.llm, "retrieve_relevant_chunks", lambda question: list(CHUNKS))

    def _generate_content(**kwargs):
        state["calls"] += 1
        if state["error"] is not None:
            raise state["error"]
        return SimpleNamespace(text=state["text"])

    monkeypatch.setattr(app.llm.client.models, "generate_content", _generate_content)
    return state


@pytest.fixture
def real_answer(monkeypatch):
    """Undo the conftest stub so /chat runs the real generate_answer (still against fakes)."""
    monkeypatch.setattr(app.main, "generate_answer", app.llm.generate_answer)


def chat_headers():
    return {"Authorization": f"Bearer {create_access_token(email='user@x.com')}"}


# --- empty / blocked model responses -------------------------------------------

@pytest.mark.parametrize("text", [None, "", "   \n\t "], ids=["none", "empty", "whitespace"])
def test_empty_model_response_returns_fallback(fake_llm, text):
    fake_llm["text"] = text
    assert app.llm.generate_answer(QUESTION) == {"answer": NO_INFO_MESSAGE, "sources": []}


# --- fallback detection clears sources ----------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        NO_INFO_MESSAGE,
        f"  {NO_INFO_MESSAGE}\n",
        f'"{NO_INFO_MESSAGE}"',
        f"'{NO_INFO_MESSAGE}'",
        f"“{NO_INFO_MESSAGE}”",
        f' \n"{NO_INFO_MESSAGE}" ',
    ],
    ids=["exact", "whitespace", "double-quotes", "single-quotes", "curly-quotes", "quotes-and-whitespace"],
)
def test_fallback_variants_clear_sources(fake_llm, text):
    fake_llm["text"] = text
    assert app.llm.generate_answer(QUESTION) == {"answer": NO_INFO_MESSAGE, "sources": []}


def test_answer_that_merely_mentions_fallback_keeps_sources(fake_llm):
    fake_llm["text"] = f"Refunds take 14 days. {NO_INFO_MESSAGE}"
    result = app.llm.generate_answer(QUESTION)
    assert result["sources"] == ["refund_policy.md", "cancel_subscription.md"]


def test_normal_answer_keeps_ordered_unique_sources(fake_llm):
    result = app.llm.generate_answer(QUESTION)
    assert result == {
        "answer": "Refunds are available within 14 days.",
        "sources": ["refund_policy.md", "cancel_subscription.md"],
    }
    assert fake_llm["calls"] == 1


# --- upstream failures → AnswerUnavailableError / 503 --------------------------

@pytest.mark.parametrize(
    "error",
    [gemini_api_error(503), genai_errors.ClientError(429, {"error": {"code": 429, "message": "quota"}}),
     httpx.ConnectError("connection refused"), httpx.ReadTimeout("timed out")],
    ids=["gemini-503", "gemini-429", "connect-error", "timeout"],
)
def test_generation_service_errors_raise_answer_unavailable(fake_llm, error):
    fake_llm["error"] = error
    with pytest.raises(AnswerUnavailableError):
        app.llm.generate_answer(QUESTION)


@pytest.mark.parametrize(
    "error",
    [ChromaInternalError("chroma down"), Exception("upstream 502 from chroma"),
     gemini_api_error(500), httpx.ConnectTimeout("timed out")],
    ids=["chroma-error", "chroma-bare-exception", "embedding-api-error", "transport-error"],
)
def test_retrieval_service_errors_raise_answer_unavailable(monkeypatch, error):
    def _fail(question):
        raise error

    monkeypatch.setattr(app.llm, "retrieve_relevant_chunks", _fail)
    with pytest.raises(AnswerUnavailableError):
        app.llm.generate_answer(QUESTION)


@pytest.mark.parametrize("error", [KeyError("documents"), TypeError("bad arg"), AttributeError("x")])
def test_programming_errors_are_not_converted(monkeypatch, error):
    def _fail(question):
        raise error

    monkeypatch.setattr(app.llm, "retrieve_relevant_chunks", _fail)
    with pytest.raises(type(error)):
        app.llm.generate_answer(QUESTION)


def test_programming_error_in_generation_is_not_converted(fake_llm):
    fake_llm["error"] = ValueError("bug in our code")
    with pytest.raises(ValueError):
        app.llm.generate_answer(QUESTION)


def test_chat_returns_503_json_when_gemini_fails(client, real_answer, fake_llm):
    fake_llm["error"] = gemini_api_error(503)
    res = client.post("/chat", json={"question": QUESTION}, headers=chat_headers())
    assert res.status_code == 503
    assert res.headers["content-type"].startswith("application/json")
    assert res.json() == UNAVAILABLE  # api.js reads data.detail from this


def test_chat_returns_503_json_when_retrieval_fails(client, real_answer, monkeypatch):
    def _fail(question):
        raise ChromaInternalError("chroma down")

    monkeypatch.setattr(app.llm, "retrieve_relevant_chunks", _fail)
    res = client.post("/chat", json={"question": QUESTION}, headers=chat_headers())
    assert res.status_code == 503
    assert res.json() == UNAVAILABLE


def test_chat_programming_error_stays_500(client, real_answer, monkeypatch):
    def _fail(question):
        raise KeyError("documents")

    monkeypatch.setattr(app.llm, "retrieve_relevant_chunks", _fail)
    with TestClient(app.main.app, raise_server_exceptions=False) as raw_client:
        res = raw_client.post("/chat", json={"question": QUESTION}, headers=chat_headers())
    assert res.status_code == 500


def test_chat_success_path_unchanged(client, real_answer, fake_llm):
    res = client.post("/chat", json={"question": QUESTION}, headers=chat_headers())
    assert res.status_code == 200
    assert res.json() == {
        "answer": "Refunds are available within 14 days.",
        "sources": ["refund_policy.md", "cancel_subscription.md"],
    }


def test_service_error_log_has_stage_and_type_but_no_question_or_body(fake_llm, capsys):
    fake_llm["error"] = gemini_api_error(503)
    with pytest.raises(AnswerUnavailableError):
        app.llm.generate_answer(QUESTION)
    log = capsys.readouterr().out
    assert "generation failed with ServerError (status 503)" in log
    assert "SECRET-QUESTION-MARKER" not in log
    assert "upstream detail" not in log
    assert "test-gemini-key" not in log


# --- prompt consistency (offline; live model behaviour unverified) -------------

def test_prompt_fallback_sentence_matches_no_info_message():
    rules = app.prompts.SYSTEM_PROMPT
    assert f'reply with exactly: "{NO_INFO_MESSAGE}"' in rules


def test_prompt_scope_rule_uses_the_fallback():
    scope_rule = next(line for line in app.prompts.SYSTEM_PROMPT.splitlines() if line.startswith("5. SCOPE LIMITATION"))
    assert "reply with exactly the fallback message from rule 4" in scope_rule
    assert "Politely decline" not in scope_rule


# --- chunker ------------------------------------------------------------------

def make_text(length):
    return "".join(chr(ord("a") + i % 26) for i in range(length))


@pytest.mark.parametrize("length", [0, 1, 450, 499, 500, 501, 881, 900, 928, 950, 988, 1400, 5000])
def test_chunker_coverage_overlap_and_no_redundant_tail(length):
    text = make_text(length)
    size, overlap = app.rag.CHUNK_SIZE, app.rag.CHUNK_OVERLAP
    chunks = app.rag.chunk_text(text)

    if length == 0:
        assert chunks == []
        return

    step = size - overlap
    for index, chunk in enumerate(chunks):
        assert chunk == text[index * step:index * step + size]  # same offsets/size as before
        assert len(chunk) <= size
    # Full coverage: first chunk starts at 0, last chunk reaches the end.
    assert text.startswith(chunks[0])
    assert (len(chunks) - 1) * step + len(chunks[-1]) == length
    # No chunk lies entirely inside the previous one.
    for previous, current in zip(chunks, chunks[1:]):
        assert len(current) > overlap


def test_chunk_settings_unchanged():
    assert (app.rag.CHUNK_SIZE, app.rag.CHUNK_OVERLAP) == (500, 50)


def test_real_docs_still_fully_covered():
    for doc in app.rag.load_documents():
        chunks = app.rag.chunk_text(doc["text"])
        step = app.rag.CHUNK_SIZE - app.rag.CHUNK_OVERLAP
        rebuilt = "".join(chunk[: step] for chunk in chunks[:-1]) + chunks[-1]
        assert rebuilt == doc["text"], doc["filename"]
