"""
Step 9 — retrieval evaluation harness (scripts/eval_retrieval.py).
All offline. These tests check the dataset labels, the metric arithmetic, and that the live
`collect` mode is guarded and read-only. They do NOT measure production retrieval quality.
"""

import inspect
import json
import math
from collections import Counter

import pytest

import app.rag
from scripts import eval_retrieval as ev
from tests.conftest import TEST_ENV, run_isolated


def row(source, distance, chunk_id=None):
    return {"chunk_id": chunk_id or f"{source}_0", "source": source, "distance": distance}


QUESTIONS = [
    {"id": "a", "category": "single", "question": "A?", "expected_sources": ["pricing.md"]},
    {"id": "b", "category": "multi", "question": "B?", "expected_sources": ["pricing.md", "refund_policy.md"]},
    {"id": "c", "category": "single", "question": "C?", "expected_sources": ["team_invites.md"]},
    {"id": "d", "category": "out_of_scope", "question": "D?", "expected_sources": []},
]
RESULTS = {
    "a": [row("pricing.md", 0.5), row("about_flowspace.md", 0.9)],
    "b": [row("pricing.md", 0.7), row("cancel_subscription.md", 0.8), row("refund_policy.md", 1.1)],
    "c": [row("pricing.md", 1.3)],
    "d": [row("pricing.md", 1.0)],
}


# --- the dataset --------------------------------------------------------------

def test_dataset_loads_and_labels_match_the_docs():
    questions = ev.load_dataset()
    assert len(questions) == 40
    counts = Counter(q["category"] for q in questions)
    assert counts == {"single": 22, "multi": 6, "ambiguous": 4, "unanswerable": 5, "out_of_scope": 3}
    doc_names = {doc["filename"] for doc in app.rag.load_documents()}
    labelled = {source for q in questions for source in q["expected_sources"]}
    assert labelled == doc_names  # every doc is covered, and nothing else is referenced
    assert all(len(q["expected_sources"]) >= 2 for q in questions if q["category"] == "multi")


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"id": "x", "category": "single", "question": "Q", "expected_sources": ["nope.md"]}, "not in docs"),
        ({"id": "x", "category": "single", "question": "Q", "expected_sources": []}, "needs expected_sources"),
        ({"id": "x", "category": "out_of_scope", "question": "Q", "expected_sources": ["pricing.md"]}, "must have no"),
        ({"id": "x", "category": "vague", "question": "Q", "expected_sources": []}, "unknown category"),
        ({"id": "x", "category": "single", "question": " ", "expected_sources": ["pricing.md"]}, "empty question"),
        ({"id": "x", "category": "multi", "question": "Q", "expected_sources": ["pricing.md", "pricing.md"]}, "without duplicates"),
    ],
)
def test_dataset_validation_rejects_bad_labels(tmp_path, bad, message):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"questions": [bad]}), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        ev.load_dataset(path)


def test_dataset_validation_rejects_duplicate_ids(tmp_path):
    q = {"id": "x", "category": "out_of_scope", "question": "Q", "expected_sources": []}
    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"questions": [q, dict(q)]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        ev.load_dataset(path)


def test_production_constants_match_app_rag():
    assert ev.PRODUCTION_THRESHOLD == app.rag.DISTANCE_THRESHOLD
    assert ev.PRODUCTION_K == inspect.signature(app.rag.retrieve_relevant_chunks).parameters["n_results"].default
    assert ev.PRODUCTION_THRESHOLD in ev.GEMINI_THRESHOLDS


# --- metric arithmetic --------------------------------------------------------

def test_retained_sources_applies_k_threshold_order_and_dedup():
    rows = [row("b.md", 0.9), row("a.md", 0.2), row("a.md", 0.3, "a.md_1"), row("c.md", 1.5)]
    assert ev.retained_sources(rows, k=3, threshold=1.0) == ["a.md", "b.md"]
    assert ev.retained_sources(rows, k=1, threshold=1.0) == ["a.md"]
    assert ev.retained_sources(rows, k=4, threshold=math.inf) == ["a.md", "b.md", "c.md"]
    assert ev.retained_sources(rows, k=3, threshold=0.1) == []


def test_score_with_hand_computed_expectations():
    result = ev.score(QUESTIONS, RESULTS, k=3, threshold=1.0)
    # a: hit (pricing). b: pricing yes, refund (1.1) filtered -> hit, recall 1/2. c: nothing passes -> gated out.
    # d: pricing at 1.0 passes -> false positive.
    assert result["answerable"] == 3 and result["unanswerable"] == 1
    assert result["hit_rate"] == pytest.approx(2 / 3)
    assert result["recall"] == pytest.approx((1 + 0.5 + 0) / 3)
    assert result["gated_out_rate"] == pytest.approx(1 / 3)
    assert result["false_positive_rate"] == 1.0
    assert [miss["id"] for miss in result["misses"]] == ["c"]
    assert result["per_category"]["multi"] == {"questions": 1, "with_chunks": 1, "hits": 1}


def test_score_with_no_threshold_and_k_1():
    result = ev.score(QUESTIONS, RESULTS, k=1, threshold=math.inf)
    assert result["hit_rate"] == pytest.approx(2 / 3)       # c's only chunk is pricing.md
    assert result["recall"] == pytest.approx((1 + 0.5 + 0) / 3)
    assert result["gated_out_rate"] == 0.0
    assert result["false_positive_rate"] == 1.0


def test_tight_threshold_gates_everything():
    result = ev.score(QUESTIONS, RESULTS, k=3, threshold=0.1)
    assert result["hit_rate"] == 0.0 and result["gated_out_rate"] == 1.0 and result["false_positive_rate"] == 0.0


def test_sweep_is_monotonic_in_threshold():
    rows = ev.sweep(QUESTIONS, RESULTS, 3, [0.1, 0.6, 0.8, 1.0, 1.2, math.inf])
    for metric in ("hit_rate", "recall", "false_positive_rate"):
        values = [r[metric] for r in rows]
        assert values == sorted(values), metric
    gated = [r["gated_out_rate"] for r in rows]
    assert gated == sorted(gated, reverse=True)


def test_missing_results_are_an_error():
    with pytest.raises(ValueError, match="No results for: d"):
        ev.score(QUESTIONS, {key: value for key, value in RESULTS.items() if key != "d"}, 3, 1.0)


# --- lexical baseline (offline) -----------------------------------------------

def test_lexical_results_rank_the_matching_chunk_first():
    ids = ["pricing.md_0", "refund_policy.md_0"]
    texts = ["Pro plan price per user per month", "Refunds are processed within business days"]
    metas = [{"source": "pricing.md"}, {"source": "refund_policy.md"}]
    questions = [{"id": "q", "question": "How long do refunds take?"}]
    results = ev.lexical_results(questions, ids, texts, metas, k=2)["q"]
    assert [r["source"] for r in results] == ["refund_policy.md", "pricing.md"]
    assert 0 <= results[0]["distance"] < results[1]["distance"] <= 1


def test_lexical_cli_runs_without_credentials_or_network():
    """Fresh interpreter, every config variable unset, outbound sockets blocked (run_isolated)."""
    result = run_isolated(
        "import runpy, sys\n"
        "sys.argv = ['eval_retrieval', 'lexical']\n"
        "runpy.run_module('scripts.eval_retrieval', run_name='__main__')\n"
        "print('CHROMA_CALLS=%d' % len(chroma_calls))\n",
        env_overrides={name: None for name in TEST_ENV},
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "Retriever: lexical-tfidf" in out and "OFFLINE BASELINE" in out
    assert "Dataset: 40 questions (32 answerable, 8 unanswerable/out-of-scope), k=3" in out
    assert "CHROMA_CALLS=0" in out


# --- report mode --------------------------------------------------------------

def test_report_mode_scores_a_saved_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ev, "load_dataset", lambda: QUESTIONS)
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"retriever": "gemini+chroma", "embedding_model": "m", "index_in_sync": True,
                                "k": 3, "collected_at": "2026-01-01T00:00:00+00:00", "results": RESULTS}))
    ev.main(["report", str(path), "--thresholds", "1.0,1.2,none"])
    out = capsys.readouterr().out
    assert "Retriever: gemini+chroma" in out and "OFFLINE BASELINE" not in out
    assert "1.2*" in out and "current production threshold" in out
    assert " 66.7%" in out


def test_report_rejects_k_larger_than_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "load_dataset", lambda: QUESTIONS)
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"retriever": "gemini+chroma", "k": 3, "results": RESULTS}))
    with pytest.raises(SystemExit):
        ev.main(["report", str(path), "--k", "5"])


# --- live collect mode: guarded and read-only (fakes only) ---------------------

def test_collect_refuses_without_confirm_live(monkeypatch, tmp_path):
    def _fail(*args, **kwargs):
        raise AssertionError("collect_live must not run without --confirm-live")

    monkeypatch.setattr(ev, "collect_live", _fail)
    with pytest.raises(SystemExit):
        ev.main(["collect", "--out", str(tmp_path / "out.json")])
    assert not (tmp_path / "out.json").exists()


class ReadOnlyCollection:
    """Only the read methods exist, so any write attempt would raise AttributeError."""

    def __init__(self, metadata):
        self.metadata = metadata
        self.queries = []

    def query(self, query_embeddings, n_results, include):
        self.queries.append(n_results)
        return {
            "ids": [["pricing.md_0", "refund_policy.md_1"][:n_results]],
            "metadatas": [[{"source": "pricing.md"}, {"source": "refund_policy.md"}][:n_results]],
            "distances": [[0.4, 0.9][:n_results]],
        }


class FakeChromaClient:
    def __init__(self, collection):
        self.collection = collection

    def get_collection(self, name):
        assert name == app.rag.COLLECTION_NAME
        return self.collection


def test_collect_live_uses_existing_collection_read_only(monkeypatch):
    fingerprint = app.rag.compute_index_fingerprint(app.rag.load_documents())
    collection = ReadOnlyCollection({app.rag.FINGERPRINT_KEY: fingerprint})
    embedded = []
    monkeypatch.setattr(app.rag, "get_chroma_client", lambda: FakeChromaClient(collection))
    monkeypatch.setattr(app.rag, "embed_text", lambda text: embedded.append(text) or [0.0, 1.0])

    saved = ev.collect_live(QUESTIONS, k=2)
    assert embedded == [q["question"] for q in QUESTIONS]
    assert collection.queries == [2] * len(QUESTIONS)
    assert saved["retriever"] == "gemini+chroma" and saved["index_in_sync"] is True and saved["k"] == 2
    assert saved["embedding_model"] == "test-embedding-model"
    assert saved["results"]["a"] == [row("pricing.md", 0.4, "pricing.md_0"), row("refund_policy.md", 0.9, "refund_policy.md_1")]
    assert ev.score(QUESTIONS, saved["results"], 2, 1.2)["answerable"] == 3


def test_collect_live_flags_a_stale_index(monkeypatch, capsys):
    collection = ReadOnlyCollection({app.rag.FINGERPRINT_KEY: "old"})
    monkeypatch.setattr(app.rag, "get_chroma_client", lambda: FakeChromaClient(collection))
    monkeypatch.setattr(app.rag, "embed_text", lambda text: [0.0])
    assert ev.collect_live(QUESTIONS[:1], k=1)["index_in_sync"] is False
    assert "does not match backend/docs" in capsys.readouterr().out
