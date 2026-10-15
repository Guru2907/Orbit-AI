"""
Step 2 — configuration: required DATABASE_URL, configurable CORS origins, Neon-safe pooling.
All offline: see conftest.py.
"""

import pytest

import app.config
import app.database
from tests.conftest import run_isolated

VERCEL_ORIGIN = "https://orbit-ai-flowspace.vercel.app"
LOCAL_ORIGIN = "http://localhost:5173"


def preflight(client, origin):
    return client.options(
        "/chat",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


# --- DATABASE_URL -------------------------------------------------------------

@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_missing_database_url_raises_clear_error(value):
    result = run_isolated("import app.config\n", env_overrides={"DATABASE_URL": value})
    assert result.returncode != 0
    assert "RuntimeError: DATABASE_URL is not set" in result.stderr


def test_engine_uses_pool_pre_ping():
    assert app.database.engine.pool._pre_ping is True


# --- CORS_ORIGINS parsing -----------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://a.example", ["https://a.example"]),
        ("https://a.example, https://b.example,", ["https://a.example", "https://b.example"]),
        ("  ,  ", []),
        ("", []),
    ],
)
def test_parse_origins(raw, expected):
    assert app.config.parse_origins(raw) == expected


def test_cors_origins_default_matches_previous_hardcoded_list():
    assert app.config.CORS_ORIGINS == [LOCAL_ORIGIN, VERCEL_ORIGIN]


# --- CORS behaviour (default origins) -----------------------------------------

@pytest.mark.parametrize("origin", [LOCAL_ORIGIN, VERCEL_ORIGIN])
def test_preflight_allowed_for_default_origins(client, origin):
    res = preflight(client, origin)
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == origin


def test_preflight_refused_for_unknown_origin(client):
    res = preflight(client, "https://evil.example")
    assert res.status_code == 400
    assert "access-control-allow-origin" not in res.headers


# --- CORS behaviour (custom CORS_ORIGINS) -------------------------------------

def test_custom_cors_origins_applied_by_app():
    result = run_isolated(
        "from fastapi.testclient import TestClient\n"
        "import app.config, app.main\n"
        "print('PARSED=' + '|'.join(app.config.CORS_ORIGINS))\n"
        "client = TestClient(app.main.app)\n"
        "def preflight(origin):\n"
        "    return client.options('/chat', headers={'Origin': origin, "
        "'Access-Control-Request-Method': 'POST'})\n"
        "print('ALLOWED_B=%s' % preflight('https://b.example').headers.get('access-control-allow-origin'))\n"
        f"print('ALLOWED_VERCEL=%s' % preflight('{VERCEL_ORIGIN}').headers.get('access-control-allow-origin'))\n"
        "print('CHROMA_CALLS=%d' % len(chroma_calls))\n",
        env_overrides={"CORS_ORIGINS": " https://a.example, https://b.example, "},
    )
    assert result.returncode == 0, result.stderr
    assert "PARSED=https://a.example|https://b.example" in result.stdout
    assert "ALLOWED_B=https://b.example" in result.stdout
    assert "ALLOWED_VERCEL=None" in result.stdout
    assert "CHROMA_CALLS=0" in result.stdout
