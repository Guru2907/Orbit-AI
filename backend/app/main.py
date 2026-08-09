from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.llm import generate_answer
from app.rag import build_index, chroma_client

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    question : str

class ChatResponse(BaseModel):
    answer: str
    sources: list[str]

@app.get("/health")
def health():
    return{"status":"ok"}

@app.post("/chat")
def chat(request: ChatRequest) -> ChatResponse:
    result = generate_answer(request.question)
    return ChatResponse(answer=result["answer"], sources=result["sources"])

@app.on_event("startup")
def startup_event():
    collection = chroma_client.get_or_create_collection(name="flowspace_docs")
    existing_count = collection.count()

    if existing_count == 0:
        print("No existing index found — building index...")
        build_index()
        print("Index ready.")
    else:
        print(f"Index already exists with {existing_count} chunks — skipping rebuild.")
