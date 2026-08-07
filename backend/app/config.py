"""
Loads environment variables once, so every other file can just import
from here instead of calling load_dotenv() everywhere.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # reads the .env file sitting next to this project

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")  # default if not set
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# Fail loudly and early if the key is missing, instead of a confusing
# error later when we actually try to call OpenAI.
if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Copy backend/.env.example to backend/.env "
        "and add your key."
    )
