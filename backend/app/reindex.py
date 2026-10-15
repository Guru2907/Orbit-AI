"""
Manually sync the Chroma index with backend/docs.
Run with: python -m app.reindex [--force]   (from inside backend/)

WARNING: this uses the real credentials in backend/.env. When the docs have changed
(or with --force) it makes paid Gemini embedding calls and writes to Chroma Cloud.
"""

import argparse

from app.rag import sync_index


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sync the Chroma index with backend/docs.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed and rewrite every chunk even if the index looks up to date.",
    )
    args = parser.parse_args(argv)
    sync_index(force=args.force)


if __name__ == "__main__":
    main()
