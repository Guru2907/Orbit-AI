"""
Loads environment variables once, so every other file can just import
from here instead of calling load_dotenv() everywhere.
"""

import os
from dotenv import load_dotenv

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
