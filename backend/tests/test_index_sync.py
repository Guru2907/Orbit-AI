"""
Step 5 — index sync and lifespan startup.
All offline: Gemini embeddings are faked, Chroma is either an in-memory FakeCollection or a
LOCAL chromadb.EphemeralClient (never Chroma Cloud). See conftest.py for the network guard.
"""

import uuid

import httpx
import pytest
from chromadb.errors import InternalError as ChromaInternalError
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors

import app.main
import app.rag
import app.reindex
from app.rag import FINGERPRINT_KEY
from tests.conftest import FakeCollection, run_isolated

DOCS = [
    {"filename": "a.md", "text": "A" * 900},   # 2 chunks
    {"filename": "b.md", "text": "B" * 300},   # 1 chunk
]


@pytest.fixture
def docs(monkeypatch):
    current = [dict(doc) for doc in DOCS]
    monkeypatch.setattr(app.rag, "load_documents", lambda: [dict(doc) for doc in current])
    return current


@pytest.fixture
def embedder(monkeypatch):
    """Fake embedder. Set state['fail_after'] = n to raise on the (n+1)-th call."""
    state = {"calls": [], "fail_after": None, "error": genai_errors.ServerError(503, {"error": {"message": "down"}})}

    def _embed(text):
        if state["fail_after"] is not None and len(state["calls"]) >= state["fail_after"]:
            raise state["error"]
        state["calls"].append(text)
        return [float(len(text)), 1.0]

    monkeypatch.setattr(app.rag, "embed_text", _embed)
    return state


@pytest.fixture
def use_collection(monkeypatch):
    def _use(collection):
        monkeypatch.setattr(app.rag, "get_collection", lambda: collection)
        return collection
    return _use


def synced_collection(docs, **kwargs):
    """A FakeCollection that already matches `docs` (as a previous successful sync would leave it)."""
    ids, texts, metas = app.rag.prepare_chunks(docs)
    records = {i: {"document": t, "metadata": m, "embedding": [0.0]} for i, t, m in zip(ids, texts, metas)}
    return FakeCollection(records=records, metadata={FINGERPRINT_KEY: app.rag.compute_index_fingerprint(docs)}, **kwargs)


# --- when to rebuild ----------------------------------------------------------

def test_empty_collection_builds_and_stores_fingerprint(docs, embedder, use_collection):
    collection = use_collection(FakeCollection())
    assert app.rag.sync_index() is True
    assert sorted(collection.records) == ["a.md_0", "a.md_1", "b.md_0"]
    assert len(embedder["calls"]) == 3
    assert collection.metadata == {FINGERPRINT_KEY: app.rag.compute_index_fingerprint(docs)}


def test_matching_fingerprint_skips_without_embedding_or_writes(docs, embedder, use_collection):
    collection = use_collection(synced_collection(docs))
    assert app.rag.sync_index() is False
    assert embedder["calls"] == []
    assert collection.writes == []


def test_matching_fingerprint_but_empty_collection_rebuilds(docs, embedder, use_collection):
    fingerprint = app.rag.compute_index_fingerprint(docs)
    collection = use_collection(FakeCollection(metadata={FINGERPRINT_KEY: fingerprint}))
    assert app.rag.sync_index() is True
    assert len(collection.records) == 3


def test_force_rebuilds_even_when_up_to_date(docs, embedder, use_collection):
    collection = use_collection(synced_collection(docs))
    assert app.rag.sync_index(force=True) is True
    assert len(embedder["calls"]) == 3
    assert "upsert" in collection.writes


def test_existing_index_without_fingerprint_is_resynced(docs, embedder, use_collection):
    """The live collection today has chunks but no fingerprint — first startup re-syncs once."""
    collection = synced_collection(docs)
    collection.metadata = None
    use_collection(collection)
    assert app.rag.sync_index() is True
    assert collection.metadata[FINGERPRINT_KEY] == app.rag.compute_index_fingerprint(docs)
    assert app.rag.sync_index() is False  # second run is a no-op


# --- what gets rebuilt --------------------------------------------------------

def test_edited_doc_is_reembedded_and_fingerprint_updated(docs, embedder, use_collection):
    collection = use_collection(synced_collection(docs))
    old_fingerprint = collection.metadata[FINGERPRINT_KEY]
    docs[1]["text"] = "C" * 300

    assert app.rag.sync_index() is True
    assert collection.records["b.md_0"]["document"] == "C" * 300
    assert collection.metadata[FINGERPRINT_KEY] != old_fingerprint


def test_shrunk_doc_stale_chunks_deleted(docs, embedder, use_collection):
    collection = use_collection(synced_collection(docs))
    docs[0]["text"] = "A" * 100  # a.md: 2 chunks -> 1
    app.rag.sync_index()
    assert sorted(collection.records) == ["a.md_0", "b.md_0"]


def test_removed_doc_chunks_deleted(docs, embedder, use_collection):
    collection = use_collection(synced_collection(docs))
    del docs[1]
    app.rag.sync_index()
    assert sorted(collection.records) == ["a.md_0", "a.md_1"]


def test_real_docs_remove_old_redundant_tail_chunk(embedder, use_collection):
    """Simulate today's live index (old chunker, no fingerprint) against the real docs."""
    real_docs = app.rag.load_documents()

    def old_chunker(text, size=500, overlap=50):
        return [text[i:i + size] for i in range(0, len(text), size - overlap)]

    old_records = {
        f"{doc['filename']}_{i}": {"document": piece, "metadata": {"source": doc["filename"]}, "embedding": [0.0]}
        for doc in real_docs
        for i, piece in enumerate(old_chunker(doc["text"]))
    }
    assert "cancel_subscription.md_2" in old_records
    collection = use_collection(FakeCollection(records=old_records))

    app.rag.sync_index()
    expected_ids, _, _ = app.rag.prepare_chunks(real_docs)
    assert "cancel_subscription.md_2" not in collection.records
    assert sorted(collection.records) == sorted(expected_ids)


def test_existing_metadata_preserved_except_hnsw_keys(docs, embedder, use_collection):
    collection = use_collection(FakeCollection(metadata={"owner": "orbit", "hnsw:space": "l2", FINGERPRINT_KEY: "old"}))
    app.rag.sync_index()
    assert collection.metadata == {"owner": "orbit", FINGERPRINT_KEY: app.rag.compute_index_fingerprint(docs)}


# --- fingerprint --------------------------------------------------------------

def test_fingerprint_independent_of_file_order():
    assert app.rag.compute_index_fingerprint(DOCS) == app.rag.compute_index_fingerprint(list(reversed(DOCS)))


@pytest.mark.parametrize(
    "change",
    ["text", "filename", "chunk_size", "chunk_overlap", "embedding_model", "index_version"],
)
def test_fingerprint_changes_when_inputs_change(monkeypatch, change):
    before = app.rag.compute_index_fingerprint(DOCS)
    docs = [dict(doc) for doc in DOCS]
    if change == "text":
        docs[0]["text"] += "!"
    elif change == "filename":
        docs[0]["filename"] = "renamed.md"
    elif change == "chunk_size":
        monkeypatch.setattr(app.rag, "CHUNK_SIZE", 400)
    elif change == "chunk_overlap":
        monkeypatch.setattr(app.rag, "CHUNK_OVERLAP", 40)
    elif change == "embedding_model":
        monkeypatch.setattr(app.rag, "EMBEDDING_MODEL", "other-model")
    elif change == "index_version":
        monkeypatch.setattr(app.rag, "INDEX_VERSION", app.rag.INDEX_VERSION + 1)
    assert app.rag.compute_index_fingerprint(docs) != before


# --- failure behaviour --------------------------------------------------------

def test_embedding_failure_leaves_chroma_untouched(docs, embedder, use_collection, capsys):
    collection = use_collection(synced_collection(docs))
    before_records = dict(collection.records)
    before_metadata = dict(collection.metadata)
    docs[1]["text"] = "changed"
    embedder["fail_after"] = 1  # first chunk embeds, second fails

    with pytest.raises(genai_errors.ServerError):
        app.rag.sync_index()

    assert collection.writes == []
    assert collection.records == before_records
    assert collection.metadata == before_metadata
    assert "aborted while embedding (ServerError); Chroma was not modified" in capsys.readouterr().out


def test_upsert_failure_keeps_old_fingerprint(docs, embedder, use_collection, capsys):
    collection = synced_collection(docs, fail_on={"upsert"}, failure=ChromaInternalError("boom"))
    old_metadata = dict(collection.metadata)
    use_collection(collection)
    docs[1]["text"] = "changed"

    with pytest.raises(ChromaInternalError):
        app.rag.sync_index()

    assert collection.metadata == old_metadata
    assert collection.writes == ["upsert"]  # nothing after the failed upsert
    assert "upsert failed (InternalError). Fingerprint not updated" in capsys.readouterr().out


def test_delete_failure_keeps_old_fingerprint_then_retry_completes(docs, embedder, use_collection, capsys):
    """Not atomic: after a failed delete, new chunks are in and stale ones remain until the retry."""
    collection = synced_collection(docs, fail_on={"delete"}, failure=httpx.ConnectError("down"))
    old_metadata = dict(collection.metadata)
    use_collection(collection)
    del docs[1]  # b.md_0 becomes stale

    with pytest.raises(httpx.ConnectError):
        app.rag.sync_index()

    assert collection.metadata == old_metadata
    assert "b.md_0" in collection.records  # stale chunk still present (partial state)
    assert "stale chunk delete failed (ConnectError)" in capsys.readouterr().out

    # Fingerprint still old -> next sync retries and finishes the job.
    assert app.rag.sync_index() is True
    assert sorted(collection.records) == ["a.md_0", "a.md_1"]
    assert collection.metadata[FINGERPRINT_KEY] == app.rag.compute_index_fingerprint(docs)


def test_stale_lookup_failure_keeps_old_fingerprint(docs, embedder, use_collection):
    collection = use_collection(synced_collection(docs, fail_on={"get"}, failure=ChromaInternalError("boom")))
    old_metadata = dict(collection.metadata)
    docs[0]["text"] = "changed"
    with pytest.raises(ChromaInternalError):
        app.rag.sync_index()
    assert collection.metadata == old_metadata
    assert "delete" not in collection.writes


def test_fingerprint_update_failure_means_next_sync_retries(docs, embedder, use_collection):
    collection = use_collection(FakeCollection(fail_on={"modify"}, failure=ChromaInternalError("boom")))
    with pytest.raises(ChromaInternalError):
        app.rag.sync_index()
    assert collection.metadata is None
    assert len(collection.records) == 3  # data written, fingerprint not
    assert app.rag.sync_index() is True  # retried, now succeeds
    assert collection.metadata[FINGERPRINT_KEY] == app.rag.compute_index_fingerprint(docs)


def test_sync_logs_contain_no_doc_text_or_keys(docs, embedder, use_collection, capsys):
    use_collection(FakeCollection())
    app.rag.sync_index()
    log = capsys.readouterr().out
    assert "Index synced: 3 chunks from 2 documents, 0 stale chunks removed." in log
    assert "AAAA" not in log and "test-gemini-key" not in log and "test-chroma-key" not in log


# --- contract test against the real (local, in-memory) Chroma client ------------

@pytest.fixture
def ephemeral_collection():
    import chromadb
    from chromadb.config import Settings

    local_client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    name = f"sync_test_{uuid.uuid4().hex[:8]}"
    collection = local_client.get_or_create_collection(name=name)
    yield local_client, name, collection
    local_client.delete_collection(name)  # local in-memory test collection only


def test_sync_against_local_chroma_client(docs, embedder, monkeypatch, ephemeral_collection):
    local_client, name, collection = ephemeral_collection
    # Re-fetch on every call, like the real get_collection(), so metadata is read fresh.
    monkeypatch.setattr(app.rag, "get_collection", lambda: local_client.get_or_create_collection(name=name))

    assert app.rag.sync_index() is True
    fresh = local_client.get_or_create_collection(name=name)
    assert sorted(fresh.get(include=[])["ids"]) == ["a.md_0", "a.md_1", "b.md_0"]
    assert fresh.metadata == {FINGERPRINT_KEY: app.rag.compute_index_fingerprint(docs)}

    embedder["calls"].clear()
    assert app.rag.sync_index() is False
    assert embedder["calls"] == []

    del docs[1]
    assert app.rag.sync_index() is True
    assert sorted(local_client.get_or_create_collection(name=name).get(include=[])["ids"]) == ["a.md_0", "a.md_1"]


# --- lifespan startup ---------------------------------------------------------

def test_lifespan_runs_sync_once(monkeypatch, fake_answer):
    calls = []
    monkeypatch.setattr(app.main, "sync_index", lambda force=False: calls.append(force))
    with TestClient(app.main.app) as test_client:
        assert test_client.get("/health").status_code == 200
    assert calls == [False]


@pytest.mark.parametrize(
    "error",
    [genai_errors.ServerError(503, {"error": {"message": "down"}}), ChromaInternalError("down"),
     httpx.ConnectError("down"), Exception("upstream 502 from chroma")],
    ids=["gemini", "chroma", "network", "chroma-bare-exception"],
)
def test_startup_survives_service_outage(monkeypatch, capsys, error):
    def _fail(force=False):
        raise error

    monkeypatch.setattr(app.main, "sync_index", _fail)
    with TestClient(app.main.app) as test_client:
        assert test_client.get("/health").status_code == 200
    log = capsys.readouterr().out
    assert f"startup index sync failed with {type(error).__name__}" in log
    assert "Starting anyway; serving the existing index." in log


@pytest.mark.parametrize("error", [KeyError("documents"), TypeError("bad"), RuntimeError("bug")])
def test_startup_fails_loudly_on_programming_error(monkeypatch, error):
    def _fail(force=False):
        raise error

    monkeypatch.setattr(app.main, "sync_index", _fail)
    with pytest.raises(type(error)):
        with TestClient(app.main.app):
            pass


def test_no_on_event_hooks_or_deprecation_warning():
    assert app.main.app.router.on_startup == []
    result = run_isolated(
        "import warnings\n"
        "with warnings.catch_warnings(record=True) as caught:\n"
        "    warnings.simplefilter('always')\n"
        "    import app.main\n"
        "print('ON_EVENT_WARNINGS=%d' % sum('on_event' in str(w.message) for w in caught))\n"
    )
    assert result.returncode == 0, result.stderr
    assert "ON_EVENT_WARNINGS=0" in result.stdout


# --- manual reindex command ---------------------------------------------------

@pytest.mark.parametrize("argv, expected_force", [([], False), (["--force"], True)])
def test_reindex_command_calls_sync(monkeypatch, argv, expected_force):
    calls = []
    monkeypatch.setattr(app.reindex, "sync_index", lambda force=False: calls.append(force))
    app.reindex.main(argv)
    assert calls == [expected_force]


def test_build_index_is_forced_sync(monkeypatch):
    calls = []
    monkeypatch.setattr(app.rag, "sync_index", lambda force=False: calls.append(force))
    app.rag.build_index()
    assert calls == [True]
