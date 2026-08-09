from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.llm import generate_answer
from app.rag import build_index, chroma_client

from app.database import engine, Base, get_db
from app.model import User
from app.auth import hash_password, create_access_token, verify_password, decode_access_token

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://orbit-ai-flowspace.vercel.app",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    answer: str
    sources: list[str]

class AuthRequest(BaseModel):
    email: str
    password: str

class AuthResponse(BaseModel):
    token: str
    email: str

@app.get("/health")
def health():
    return {"status": "ok"}

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

@app.post("/signup")
def signup(request: AuthRequest, db=Depends(get_db)) -> AuthResponse:
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = hash_password(request.password)

    new_user = User(email=request.email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token = create_access_token(email=request.email)
    return AuthResponse(token=token, email=request.email)

@app.post("/login")
def login(request: AuthRequest, db=Depends(get_db)) -> AuthResponse:
    existing_user = db.query(User).filter(User.email == request.email).first()
    if not existing_user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    password_matches = verify_password(request.password, existing_user.hashed_password)
    if not password_matches:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(email=request.email)
    return AuthResponse(token=token, email=request.email)

def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization.split(" ")[1]

    try:
        email = decode_access_token(token=token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return email

@app.post("/chat")
def chat(request: ChatRequest, user_email: str = Depends(get_current_user)) -> ChatResponse:
    result = generate_answer(request.question)
    return ChatResponse(answer=result["answer"], sources=result["sources"])