"""
Retrieval-quality evaluation against backend/eval/retrieval_questions.json.
Run from inside backend/.

  python -m scripts.eval_retrieval lexical [--out FILE]
      OFFLINE. Real docs and the real chunker, but a simple TF-IDF word-overlap retriever
      instead of Gemini + Chroma. Use it to check the harness and the dataset labels. Its
      numbers say nothing about the production retriever, and its distances (1 - cosine)
      are on a different scale from Chroma's.

  python -m scripts.eval_retrieval report FILE
      OFFLINE. Scores retrieval results saved earlier (by `collect` or `lexical --out`).

  python -m scripts.eval_retrieval collect --out FILE --confirm-live
      LIVE, NOT part of any test run. Uses the real credentials in backend/.env: embeds each
      question with Gemini (one paid call per question) and queries the existing Chroma Cloud
      collection. Read-only on Chroma: no upsert, delete, reindex, or collection creation.
      Saves the raw top-k results with distances, so thresholds can be compared offline.
"""

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = BACKEND_DIR / "eval" / "retrieval_questions.json"
DOCS_DIR = BACKEND_DIR / "docs"

# Mirrors app.rag (n_results=3 in retrieve_relevant_chunks, DISTANCE_THRESHOLD); a test keeps them in step.
PRODUCTION_K = 3
PRODUCTION_THRESHOLD = 1.2
COLLECT_K = 10  # collect more than production uses, so k can be varied offline later

GEMINI_THRESHOLDS = [0.6, 0.8, 1.0, 1.1, 1.2, 1.3, 1.4, math.inf]
LEXICAL_THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, math.inf]

ANSWERABLE = ("single", "multi", "ambiguous")
UNANSWERABLE = ("unanswerable", "out_of_scope")

LEXICAL_RETRIEVER = "lexical-tfidf"
LIVE_RETRIEVER = "gemini+chroma"

# Every variable app.config requires. See import_rag_offline().
REQUIRED_CONFIG = (
    "GEMINI_API_KEY", "LLM_MODEL", "EMBEDDING_MODEL", "CHROMA_API_KEY",
    "CHROMA_TENANT", "CHROMA_DATABASE", "JWT_SECRET", "DATABASE_URL",
)


# --- dataset ------------------------------------------------------------------

def load_dataset(path=DATASET_PATH, docs_dir=DOCS_DIR):
    """Loads the questions and checks every label against the docs folder."""
    with open(path, "r", encoding="utf-8") as f:
        questions = json.load(f)["questions"]

    doc_names = {name for name in os.listdir(docs_dir) if name.endswith(".md")}
    seen_ids = set()
    for q in questions:
        qid = q.get("id")
        if not qid or qid in seen_ids:
            raise ValueError(f"Missing or duplicate question id: {qid!r}")
        seen_ids.add(qid)
        if not q.get("question", "").strip():
            raise ValueError(f"{qid}: empty question")
        expected = q.get("expected_sources")
        if not isinstance(expected, list) or len(set(expected)) != len(expected):
            raise ValueError(f"{qid}: expected_sources must be a list without duplicates")
        unknown = set(expected) - doc_names
        if unknown:
            raise ValueError(f"{qid}: expected_sources not in docs/: {sorted(unknown)}")
        if q.get("category") in ANSWERABLE:
            if not expected:
                raise ValueError(f"{qid}: answerable question needs expected_sources")
        elif q.get("category") in UNANSWERABLE:
            if expected:
                raise ValueError(f"{qid}: unanswerable question must have no expected_sources")
        else:
            raise ValueError(f"{qid}: unknown category {q.get('category')!r}")
    return questions


# --- scoring ------------------------------------------------------------------

def retained_sources(rows, k, threshold):
    """What the app would cite: unique sources among the top-k chunks within the threshold."""
    sources = []
    for row in sorted(rows, key=lambda r: r["distance"])[:k]:
        if row["distance"] <= threshold and row["source"] not in sources:
            sources.append(row["source"])
    return sources


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def score(questions, results, k, threshold):
    """
    hit_rate:            answerable questions with at least one expected doc retrieved
    recall:              mean fraction of each answerable question's expected docs retrieved
    gated_out_rate:      answerable questions where nothing passes the threshold (app returns
                         the fallback without calling the LLM)
    false_positive_rate: unanswerable questions where something passes the threshold (the LLM
                         is called with unrelated context and must fall back on its own)
    """
    missing = [q["id"] for q in questions if q["id"] not in results]
    if missing:
        raise ValueError(f"No results for: {', '.join(missing)}")

    totals = Counter()
    per_category = {}
    misses = []
    for q in questions:
        got = retained_sources(results[q["id"]], k, threshold)
        expected = set(q["expected_sources"])
        category = per_category.setdefault(q["category"], Counter())
        category["questions"] += 1
        category["with_chunks"] += bool(got)
        if expected:
            found = expected & set(got)
            totals["answerable"] += 1
            totals["hits"] += bool(found)
            totals["recall"] += len(found) / len(expected)
            totals["gated_out"] += not got
            category["hits"] += bool(found)
            if not found:
                misses.append({"id": q["id"], "question": q["question"], "expected": sorted(expected), "retrieved": got})
        else:
            totals["unanswerable"] += 1
            totals["false_positives"] += bool(got)

    return {
        "k": k,
        "threshold": threshold,
        "answerable": totals["answerable"],
        "unanswerable": totals["unanswerable"],
        "hit_rate": ratio(totals["hits"], totals["answerable"]),
        "recall": ratio(totals["recall"], totals["answerable"]),
        "gated_out_rate": ratio(totals["gated_out"], totals["answerable"]),
        "false_positive_rate": ratio(totals["false_positives"], totals["unanswerable"]),
        "per_category": {name: dict(counts) for name, counts in per_category.items()},
        "misses": misses,
    }


def sweep(questions, results, k, thresholds):
    return [score(questions, results, k, threshold) for threshold in thresholds]


# --- lexical (offline) retriever ------------------------------------------------

STOPWORDS = set(
    "a an and are as at be by can do does for from has have how i if in is it its my of on or "
    "so that the their then there these this to was what when where which who will with you your".split()
)


def tokenize(text):
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in STOPWORDS]


def lexical_results(questions, chunk_ids, chunk_texts, chunk_metadatas, k):
    """TF-IDF cosine over the real chunks. distance = 1 - cosine similarity (0 = identical)."""
    chunk_counts = [Counter(tokenize(text)) for text in chunk_texts]
    n = len(chunk_counts)
    doc_freq = Counter(term for counts in chunk_counts for term in counts)
    unseen_idf = math.log(1 + n) + 1

    def vector(counts):
        return {term: count * (math.log((1 + n) / (1 + doc_freq[term])) + 1 if term in doc_freq else unseen_idf)
                for term, count in counts.items()}

    def cosine(a, b):
        dot = sum(weight * b.get(term, 0.0) for term, weight in a.items())
        norm = math.sqrt(sum(w * w for w in a.values())) * math.sqrt(sum(w * w for w in b.values()))
        return dot / norm if norm else 0.0

    chunk_vectors = [vector(counts) for counts in chunk_counts]
    results = {}
    for q in questions:
        query = vector(Counter(tokenize(q["question"])))
        rows = [
            {"chunk_id": chunk_id, "source": metadata["source"], "distance": round(1 - cosine(query, chunk_vector), 6)}
            for chunk_id, metadata, chunk_vector in zip(chunk_ids, chunk_metadatas, chunk_vectors)
        ]
        rows.sort(key=lambda row: (row["distance"], row["chunk_id"]))
        results[q["id"]] = rows[:k]
    return results


def import_rag_offline():
    """
    app.rag imports app.config, which requires credentials and loads backend/.env.
    load_dotenv() never overrides variables that are already set, so filling every required
    variable with a placeholder first keeps the real values out of this process. Importing
    app.rag makes no network calls (the Chroma client is only created on first use).
    """
    if "app.rag" not in sys.modules:
        for name in REQUIRED_CONFIG:
            os.environ[name] = "offline-eval-placeholder"
    import app.rag
    return app.rag


def run_lexical(questions, k=PRODUCTION_K):
    rag = import_rag_offline()
    chunk_ids, chunk_texts, chunk_metadatas = rag.prepare_chunks(rag.load_documents())
    return {
        "retriever": LEXICAL_RETRIEVER,
        "k": k,
        "results": lexical_results(questions, chunk_ids, chunk_texts, chunk_metadatas, k),
    }


# --- live collection (never run by tests against real services) -----------------

def collect_live(questions, k=COLLECT_K):
    from app.config import EMBEDDING_MODEL
    from app.rag import COLLECTION_NAME, FINGERPRINT_KEY, compute_index_fingerprint, embed_text, get_chroma_client, load_documents

    # get_collection, not get_or_create_collection: a missing collection is an error, not a write.
    collection = get_chroma_client().get_collection(name=COLLECTION_NAME)
    index_in_sync = (collection.metadata or {}).get(FINGERPRINT_KEY) == compute_index_fingerprint(load_documents())
    if not index_in_sync:
        print("WARNING: the Chroma index does not match backend/docs; results describe the stale index.")

    results = {}
    for q in questions:
        response = collection.query(
            query_embeddings=[embed_text(q["question"])],
            n_results=k,
            include=["metadatas", "distances"],
        )
        results[q["id"]] = [
            {"chunk_id": chunk_id, "source": metadata["source"], "distance": distance}
            for chunk_id, metadata, distance in zip(response["ids"][0], response["metadatas"][0], response["distances"][0])
        ]
    return {
        "retriever": LIVE_RETRIEVER,
        "embedding_model": EMBEDDING_MODEL,
        "index_in_sync": index_in_sync,
        "k": k,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": results,
    }


# --- output -------------------------------------------------------------------

def percent(value):
    return "  n/a" if value is None else f"{value * 100:5.1f}%"


def format_report(questions, saved, k, thresholds):
    retriever = saved.get("retriever", "unknown")
    rows = sweep(questions, saved["results"], k, thresholds)
    first = rows[0]
    lines = [f"Retriever: {retriever}"]
    if retriever == LEXICAL_RETRIEVER:
        lines.append("  OFFLINE BASELINE: not Gemini/Chroma. Distances are 1 - cosine and are not comparable")
        lines.append("  to the production threshold. Do not tune DISTANCE_THRESHOLD from these numbers.")
    else:
        lines.append(f"  embedding_model={saved.get('embedding_model')}  index_in_sync={saved.get('index_in_sync')}"
                     f"  collected_at={saved.get('collected_at')}")
    lines.append(f"Dataset: {len(questions)} questions ({first['answerable']} answerable, "
                 f"{first['unanswerable']} unanswerable/out-of-scope), k={k}")
    lines.append("")
    lines.append(f"{'threshold':>10}  {'hit@k':>6}  {'recall@k':>8}  {'gated-out':>9}  {'false-pos':>9}")
    for row in rows:
        label = "none" if math.isinf(row["threshold"]) else f"{row['threshold']:g}"
        if retriever != LEXICAL_RETRIEVER and row["threshold"] == PRODUCTION_THRESHOLD:
            label += "*"
        lines.append(f"{label:>10}  {percent(row['hit_rate']):>6}  {percent(row['recall']):>8}  "
                     f"{percent(row['gated_out_rate']):>9}  {percent(row['false_positive_rate']):>9}")
    if retriever != LEXICAL_RETRIEVER:
        lines.append("  * current production threshold")

    unthresholded = score(questions, saved["results"], k, math.inf)
    lines.append("")
    lines.append("Per category, no threshold (questions with an expected doc in the top k):")
    for name in ANSWERABLE:
        counts = unthresholded["per_category"].get(name)
        if counts:
            lines.append(f"  {name:<10} {counts['hits']}/{counts['questions']}")
    if unthresholded["misses"]:
        lines.append("Misses, no threshold:")
        for miss in unthresholded["misses"]:
            lines.append(f"  {miss['id']} expected {miss['expected']} got {miss['retrieved']}  ({miss['question']})")
    return "\n".join(lines)


def parse_thresholds(value):
    return [math.inf if part.strip() in ("none", "inf") else float(part) for part in value.split(",")]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Retrieval-quality evaluation (see module docstring).")
    sub = parser.add_subparsers(dest="mode", required=True)

    lexical = sub.add_parser("lexical", help="offline TF-IDF baseline over the real docs")
    lexical.add_argument("--out", help="also save the retrieval results to this JSON file")

    report = sub.add_parser("report", help="score saved retrieval results (offline)")
    report.add_argument("results_file")

    collect = sub.add_parser("collect", help="LIVE: query Gemini + Chroma Cloud and save raw results")
    collect.add_argument("--out", required=True)
    collect.add_argument("--k", type=int, default=COLLECT_K)
    collect.add_argument("--confirm-live", action="store_true",
                         help="required: acknowledges paid Gemini calls and reads from Chroma Cloud")

    for mode_parser in (lexical, report):
        mode_parser.add_argument("--k", type=int, default=PRODUCTION_K)
        mode_parser.add_argument("--thresholds", type=parse_thresholds,
                                 help='comma-separated, e.g. "0.8,1.0,1.2,none"')

    args = parser.parse_args(argv)
    questions = load_dataset()

    if args.mode == "collect":
        if not args.confirm_live:
            parser.error("collect makes paid Gemini calls and reads Chroma Cloud; pass --confirm-live to run it")
        saved = collect_live(questions, k=args.k)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(saved, f, indent=2)
        print(f"Saved {len(saved['results'])} results to {args.out}. Score them with: "
              f"python -m scripts.eval_retrieval report {args.out}")
        return

    if args.mode == "lexical":
        saved = run_lexical(questions, k=args.k)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2)
    else:
        with open(args.results_file, "r", encoding="utf-8") as f:
            saved = json.load(f)

    if args.k > saved.get("k", args.k):
        parser.error(f"--k {args.k} is larger than the {saved['k']} results saved per question")
    default = LEXICAL_THRESHOLDS if saved.get("retriever") == LEXICAL_RETRIEVER else GEMINI_THRESHOLDS
    print(format_report(questions, saved, args.k, args.thresholds or default))


if __name__ == "__main__":
    main()
