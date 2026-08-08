"""
Quick manual test — confirms rag.py works before wiring it into FastAPI.
Run with: python -m tests.test_chat   (from inside backend/)
"""

from app.rag import build_index, retrieve_relevant_chunks, get_unique_sources

print("Building index...")
build_index()

question = "How do I cancel my subscription?"
print(f"\nQuestion: {question}")

results = retrieve_relevant_chunks(question)

print(f"\nTop {len(results)} matching chunks:\n")
for i, chunk in enumerate(results):
    print(f"--- Result {i+1} (source: {chunk['source']}, distance: {chunk['distance']:.4f}) ---")
    print(chunk["text"][:200])
    print()

sources = get_unique_sources(results)
print(f"Unique sources: {sources}")