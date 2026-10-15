"""
Offline test harness.

Everything at module level here runs before any `app` module is imported, so:
- backend/.env is never loaded (load_dotenv is replaced with a no-op)
- every config value is a dummy, and DATABASE_URL points at in-memory SQLite
- constructing a Chroma CloudClient raises instead of connecting
- outbound sockets are blocked (loopback is allowed for asyncio's internal socketpair)
"""

import os
import socket

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False

TEST_ENV = {
    "GEMINI_API_KEY": "test-gemini-key",
    "LLM_MODEL": "test-llm-model",
    "EMBEDDING_MODEL": "test-embedding-model",
    "CHROMA_API_KEY": "test-chroma-key",
    "CHROMA_TENANT": "test-tenant",
    "CHROMA_DATABASE": "test-database",
    "JWT_SECRET": "test-jwt-secret-not-used-anywhere-real",
    "DATABASE_URL": "sqlite://",
}
os.environ.update(TEST_ENV)
os.environ.pop("CORS_ORIGINS", None)

import chromadb

CHROMA_CLIENT_CALLS = []


def _blocked_cloud_client(*args, **kwargs):
    CHROMA_CLIENT_CALLS.append((args, kwargs))
    raise RuntimeError("Tests must not construct a Chroma CloudClient")


chromadb.CloudClient = _blocked_cloud_client

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_original_connect = socket.socket.connect


def _guarded_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if host not in LOOPBACK_HOSTS:
        raise RuntimeError(f"Tests must not open network connections (attempted {address!r})")
    return _original_connect(self, address)


socket.socket.connect = _guarded_connect

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database
import app.main
from app.database import Base, get_db

assert str(app.database.engine.url) == "sqlite://", "Refusing to run tests against a non-test database"

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.main.app.dependency_overrides[get_db] = override_get_db


BACKEND_DIR = Path(__file__).resolve().parent.parent

ISOLATION_PRELUDE = (
    "import socket\n"
    "_connect = socket.socket.connect\n"
    "def _guard(self, address):\n"
    "    host = address[0] if isinstance(address, tuple) else address\n"
    "    if host not in ('127.0.0.1', '::1', 'localhost'):\n"
    "        raise RuntimeError('network blocked: %r' % (address,))\n"
    "    return _connect(self, address)\n"
    "socket.socket.connect = _guard\n"
    "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"
    "import chromadb\n"
    "chroma_calls = []\n"
    "chromadb.CloudClient = lambda *a, **k: chroma_calls.append(1)\n"
)


def run_isolated(script, env_overrides=None):
    """
    Runs `script` in a fresh interpreter (so app.config re-reads the environment) with
    the same safeguards as this conftest. A value of None in env_overrides unsets that variable.
    """
    env = {**os.environ, **TEST_ENV}
    env.pop("CORS_ORIGINS", None)
    for key, value in (env_overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, "-c", ISOLATION_PRELUDE + script],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


class FakeCollection:
    """
    In-memory stand-in for a Chroma collection. Mirrors the installed client's behaviour
    that matters here: modify(metadata=...) REPLACES all metadata (checked against a local
    chromadb.EphemeralClient). `fail_on` makes the named method raise `failure` once.
    """

    def __init__(self, records=None, metadata=None, fail_on=(), failure=None):
        self.records = dict(records or {})
        self.metadata = metadata
        self.fail_on = set(fail_on)
        self.failure = failure or RuntimeError("fake collection failure")
        self.calls = []

    def _maybe_fail(self, name):
        if name in self.fail_on:
            self.fail_on.discard(name)
            raise self.failure

    def count(self):
        self.calls.append("count")
        return len(self.records)

    def upsert(self, ids, documents, metadatas, embeddings):
        self.calls.append("upsert")
        self._maybe_fail("upsert")
        for id_, document, metadata, embedding in zip(ids, documents, metadatas, embeddings):
            self.records[id_] = {"document": document, "metadata": metadata, "embedding": embedding}

    def get(self, include=None):
        self.calls.append("get")
        self._maybe_fail("get")
        return {"ids": list(self.records)}

    def delete(self, ids):
        self.calls.append("delete")
        self._maybe_fail("delete")
        for id_ in ids:
            self.records.pop(id_, None)

    def modify(self, metadata=None):
        self.calls.append("modify")
        self._maybe_fail("modify")
        self.metadata = metadata

    @property
    def writes(self):
        return [call for call in self.calls if call in ("upsert", "delete", "modify")]


@pytest.fixture
def fake_answer(monkeypatch):
    calls = []

    def _generate_answer(question):
        calls.append(question)
        return {"answer": "Mocked answer", "sources": ["pricing.md"]}

    monkeypatch.setattr(app.main, "generate_answer", _generate_answer)
    return calls


@pytest.fixture
def client(monkeypatch, fake_answer):
    """TestClient with a fresh empty database and the startup indexing stubbed out."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    monkeypatch.setattr(app.main, "sync_index", lambda force=False: False)
    with TestClient(app.main.app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=test_engine)
