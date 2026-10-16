"""
Loads environment variables once, so every other file can just import
from here instead of calling load_dotenv() everywhere.
"""

import os
from dotenv import load_dotenv
from app.rate_limit import parse_rate_limit

load_dotenv()  

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY")
CHROMA_TENANT = os.getenv("CHROMA_TENANT")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE")
JWT_SECRET = os.getenv("JWT_SECRET")
DATABASE_URL = os.getenv("DATABASE_URL")

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "https://orbit-ai-flowspace.vercel.app",
]


def parse_origins(value):
    """Splits a comma-separated CORS_ORIGINS value, ignoring blanks and stray spaces."""
    return [origin.strip() for origin in value.split(",") if origin.strip()]


CORS_ORIGINS = parse_origins(os.getenv("CORS_ORIGINS", "")) or DEFAULT_CORS_ORIGINS

# Rate limits, as "<requests>/<seconds>". See app/rate_limit.py for what they do and don't cover.
CHAT_RATE_LIMIT = parse_rate_limit(os.getenv("CHAT_RATE_LIMIT") or "20/60", "CHAT_RATE_LIMIT")
LOGIN_RATE_LIMIT = parse_rate_limit(os.getenv("LOGIN_RATE_LIMIT") or "10/60", "LOGIN_RATE_LIMIT")
LOGIN_FAILURE_LIMIT = parse_rate_limit(os.getenv("LOGIN_FAILURE_LIMIT") or "5/900", "LOGIN_FAILURE_LIMIT")

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
        "and add your key."
    )

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is not set. Add it to backend/.env")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add your Postgres connection string to backend/.env"
    )
