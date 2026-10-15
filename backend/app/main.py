from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.llm import generate_answer, AnswerUnavailableError, is_service_error, log_service_error
from app.rag import sync_index

from app.config import CORS_ORIGINS
from app.database import engine, Base, get_db
from app.model import User
from app.auth import hash_password, create_access_token, verify_password, decode_access_token

Base.metadata.create_all(bind=engine)

def startup_event():
    """Syncs the index; if Gemini/Chroma is down, starts anyway with the existing index."""
    try:
        sync_index()
    except Exception as error:
        if not is_service_error(error):
            raise
        log_service_error("startup index sync", error)
        print("Starting anyway; serving the existing index.")

@asynccontextmanager
async def lifespan(app):
    startup_event()
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """
    Same {"detail": [...]} shape as FastAPI's default 422, but without the submitted
    `input` (which would echo passwords back) or `ctx`. Only type, location, and message.
    """
    errors = [
        {
            "type": error.get("type"),
            "loc": [part if isinstance(part, (str, int)) else str(part) for part in error.get("loc", ())],
            "msg": error.get("msg"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})

MAX_EMAIL_LENGTH = 254
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt ignores everything past 72 bytes
MAX_QUESTION_LENGTH = 1000
ANSWER_UNAVAILABLE_DETAIL = "Orbit is temporarily unavailable. Please try again."

def normalize_email(value):
    email = value.strip().lower()
    local, _, domain = email.partition("@")
    if (
        not local
        or not domain
        or "@" in domain
        or any(char.isspace() for char in email)
        or len(email) > MAX_EMAIL_LENGTH
    ):
        raise ValueError("Enter a valid email address")
    return email

class ChatRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def check_question(cls, value):
        question = value.strip()
        if not question:
            raise ValueError("Question cannot be empty")
        if len(question) > MAX_QUESTION_LENGTH:
            raise ValueError(f"Question must be at most {MAX_QUESTION_LENGTH} characters")
        return question

class ChatResponse(BaseModel):
    answer: str
    sources: list[str]

class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def check_email(cls, value):
        return normalize_email(value)

    @field_validator("password")
    @classmethod
    def check_password_bytes(cls, value):
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
        return value

class SignupRequest(LoginRequest):
    @field_validator("password")
    @classmethod
    def check_password_length(cls, value):
        if len(value) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        return value

class AuthResponse(BaseModel):
    token: str
    email: str

@app.get("/health")
def health():
    return {"status": "ok"}

def find_users_by_email(db, email):
    """Case-insensitive lookup. Returns at most 2 rows so callers can detect case-variant duplicates."""
    return db.query(User).filter(func.lower(User.email) == email).limit(2).all()

@app.post("/signup")
def signup(request: SignupRequest, db=Depends(get_db)) -> AuthResponse:
    if find_users_by_email(db, request.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = hash_password(request.password)

    new_user = User(email=request.email, hashed_password=hashed_password)
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        # Another signup for the same email committed between our check and insert.
        db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")
    db.refresh(new_user)

    token = create_access_token(email=new_user.email)
    return AuthResponse(token=token, email=new_user.email)

@app.post("/login")
def login(request: LoginRequest, db=Depends(get_db)) -> AuthResponse:
    matching_users = find_users_by_email(db, request.email)
    if len(matching_users) > 1:
        # Legacy accounts that differ only by email case: refuse rather than pick one.
        user_ids = [user.id for user in matching_users]
        print(f"Login refused: user ids {user_ids} share a case-insensitive email.")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not matching_users:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    existing_user = matching_users[0]
    password_matches = verify_password(request.password, existing_user.hashed_password)
    if not password_matches:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(email=existing_user.email)
    return AuthResponse(token=token, email=existing_user.email)

def get_current_user(authorization: str | None = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme != "Bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    try:
        email = decode_access_token(token=token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return email

@app.post("/chat")
def chat(request: ChatRequest, user_email: str = Depends(get_current_user)) -> ChatResponse:
    try:
        result = generate_answer(request.question)
    except AnswerUnavailableError:
        raise HTTPException(status_code=503, detail=ANSWER_UNAVAILABLE_DETAIL)
    return ChatResponse(answer=result["answer"], sources=result["sources"])