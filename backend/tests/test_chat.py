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

print("\n\n=== Testing llm.py ===\n")

from app.llm import generate_answer

# Test 1 — a question that SHOULD be answered from the docs
result = generate_answer("How do I cancel my subscription?")
print("Question: How do I cancel my subscription?")
print(f"Answer: {result['answer']}")
print(f"Sources: {result['sources']}")

print()

# Test 2 — a question that should trigger the fallback
result2 = generate_answer("What is the capital of France?")
print("Question: What is the capital of France?")
print(f"Answer: {result2['answer']}")
print(f"Sources: {result2['sources']}")