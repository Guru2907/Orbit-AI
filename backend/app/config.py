"""
Loads environment variables once, so every other file can just import
from here instead of calling load_dotenv() everywhere.
"""

import os
from dotenv import load_dotenv

load_dotenv()  

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5-mini")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")


if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Copy backend/.env.example to backend/.env "
        "and add your key."
    )
