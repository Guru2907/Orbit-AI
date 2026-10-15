"""
Handles loading Flowspace docs, splitting them into chunks,
and storing/searching them in Chroma Cloud.
"""

import hashlib
import json
import os
from functools import lru_cache
import chromadb
from google import genai
from app.config import CHROMA_API_KEY, CHROMA_DATABASE, CHROMA_TENANT, GEMINI_API_KEY, EMBEDDING_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)

COLLECTION_NAME = "flowspace_docs"


@lru_cache(maxsize=1)
def get_chroma_client():
    """Connects to Chroma Cloud on first use, not at import (CloudClient makes network calls)."""
    return chromadb.CloudClient(
        api_key=CHROMA_API_KEY,
        tenant=CHROMA_TENANT,
        database=CHROMA_DATABASE,
    )


def get_collection():
    return get_chroma_client().get_or_create_collection(name=COLLECTION_NAME)


DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50         
DISTANCE_THRESHOLD = 1.2

# Bump INDEX_VERSION to force a re-sync after changing how chunks are built.
INDEX_VERSION = 1
FINGERPRINT_KEY = "index_fingerprint"


def load_documents():
    documents = []
    for filename in os.listdir(DOCS_DIR):
        if filename.endswith(".md"):
            path = os.path.join(DOCS_DIR, filename)
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            documents.append({"filename": filename, "text": text})
    return documents


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(text), step):
        chunks.append(text[i:i + chunk_size])
        # Stop once a chunk reaches the end; another one would sit entirely inside this one.
        if i + chunk_size >= len(text):
            break
    return chunks


def embed_text(text):
    response = client.models.embed_content(model=EMBEDDING_MODEL, contents=text)
    return response.embeddings[0].values


def compute_index_fingerprint(documents):
    """Hash of everything that determines the index contents. Any change means a re-sync."""
    payload = {
        "index_version": INDEX_VERSION,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "embedding_model": EMBEDDING_MODEL,
        "documents": sorted([doc["filename"], doc["text"]] for doc in documents),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prepare_chunks(documents):
    chunk_ids = []
    chunk_texts = []
    chunk_metadatas = []
    for doc in documents:
        for i, piece in enumerate(chunk_text(doc["text"])):
            chunk_ids.append(f"{doc['filename']}_{i}")
            chunk_texts.append(piece)
            chunk_metadatas.append({"source": doc["filename"]})
    return chunk_ids, chunk_texts, chunk_metadatas


def sync_index(force=False):
    """
    Brings the Chroma collection in line with backend/docs. Returns True if it wrote anything.

    Order matters:
    1. Embed every chunk first — if Gemini fails, Chroma has not been touched.
    2. Upsert the new chunks, then delete chunk ids that no longer exist.
    3. Store the fingerprint last — if step 2 fails part-way, the old fingerprint stays,
       so the next sync retries. Step 2 is not atomic: a failure there can leave a mix of
       new chunks and not-yet-deleted stale chunks until the retry succeeds.
    """
    documents = load_documents()
    fingerprint = compute_index_fingerprint(documents)
    collection = get_collection()
    existing_metadata = collection.metadata or {}

    if not force and existing_metadata.get(FINGERPRINT_KEY) == fingerprint and collection.count() > 0:
        print("Index is up to date — skipping sync.")
        return False

    chunk_ids, chunk_texts, chunk_metadatas = prepare_chunks(documents)

    try:
        chunk_embeddings = [embed_text(piece) for piece in chunk_texts]
    except Exception as error:
        print(f"Index sync aborted while embedding ({type(error).__name__}); Chroma was not modified.")
        raise

    stage = "upsert"
    try:
        collection.upsert(
            ids=chunk_ids,
            documents=chunk_texts,
            metadatas=chunk_metadatas,
            embeddings=chunk_embeddings,
        )
        stage = "stale chunk lookup"
        stale_ids = sorted(set(collection.get(include=[])["ids"]) - set(chunk_ids))
        if stale_ids:
            stage = "stale chunk delete"
            collection.delete(ids=stale_ids)
        stage = "fingerprint update"
        # modify() replaces all collection metadata, so carry over existing keys.
        # hnsw:* keys can't be passed to modify(), so they are left out.
        new_metadata = {
            key: value for key, value in existing_metadata.items() if not key.startswith("hnsw:")
        }
        new_metadata[FINGERPRINT_KEY] = fingerprint
        collection.modify(metadata=new_metadata)
    except Exception as error:
        print(
            f"Index sync incomplete: {stage} failed ({type(error).__name__}). "
            "Fingerprint not updated, so the next sync will retry."
        )
        raise

    print(
        f"Index synced: {len(chunk_ids)} chunks from {len(documents)} documents, "
        f"{len(stale_ids)} stale chunks removed."
    )
    return True


def build_index():
    """Forces a full re-embed and sync. Kept for scripts/live_smoke.py."""
    return sync_index(force=True)


def retrieve_relevant_chunks(question, n_results=3):
    question_embedding = embed_text(question)

    collection = get_collection()
    results = collection.query(
        query_embeddings=[question_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    for text, metadata, distance in zip(docs, metas, distances):
        if distance <= DISTANCE_THRESHOLD:
            chunks.append({"text": text, "source": metadata["source"], "distance": distance})

    return chunks


def get_unique_sources(chunks):
    """Returns source filenames with duplicates removed, order preserved."""
    seen = set()
    unique_sources = []
    for chunk in chunks:
        if chunk["source"] not in seen:
            seen.add(chunk["source"])
            unique_sources.append(chunk["source"])
    return unique_sources