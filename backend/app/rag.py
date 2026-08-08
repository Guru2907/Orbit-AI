"""
Handles loading Flowspace docs, splitting them into chunks,
and storing/searching them in Chroma Cloud.
"""

import os
import chromadb
from google import genai
from app.config import CHROMA_API_KEY, CHROMA_DATABASE, CHROMA_TENANT, GEMINI_API_KEY, EMBEDDING_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)

chroma_client = chromadb.CloudClient(
    api_key=CHROMA_API_KEY,
    tenant=CHROMA_TENANT,
    database=CHROMA_DATABASE,
)

DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50         
DISTANCE_THRESHOLD = 1.2    


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
    return chunks


def embed_text(text):
    response = client.models.embed_content(model=EMBEDDING_MODEL, contents=text)
    return response.embeddings[0].values


def build_index():
    documents = load_documents()

    chunk_texts = []
    chunk_ids = []
    chunk_metadatas = []
    chunk_embeddings = []

    for doc in documents:
        pieces = chunk_text(doc["text"])
        for i, piece in enumerate(pieces):
            chunk_id = f"{doc['filename']}_{i}"
            chunk_texts.append(piece)
            chunk_ids.append(chunk_id)
            chunk_metadatas.append({"source": doc["filename"]})
            chunk_embeddings.append(embed_text(piece))

    collection = chroma_client.get_or_create_collection(name="flowspace_docs")
    collection.upsert(
        ids=chunk_ids,
        documents=chunk_texts,
        metadatas=chunk_metadatas,
        embeddings=chunk_embeddings,
    )
    print(f"Indexed {len(chunk_texts)} chunks from {len(documents)} documents.")


def retrieve_relevant_chunks(question, n_results=3):
    question_embedding = embed_text(question)

    collection = chroma_client.get_or_create_collection(name="flowspace_docs")
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