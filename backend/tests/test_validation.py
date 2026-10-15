"""
Step 3 — server-side input validation: passwords, emails, duplicate accounts,
chat question length, and the Authorization header. All offline: see conftest.py.
"""

import pytest

import app.main
from app.auth import create_access_token, decode_access_token, hash_password
from app.model import User
from tests.conftest import TestSessionLocal

INVALID_LOGIN = {"detail": "Invalid email or password"}


def seed_user(email, password):
    """Insert a user directly, bypassing the API — simulates accounts created before Step 3."""
    db = TestSessionLocal()
    try:
        db.add(User(email=email, hashed_password=hash_password(password)))
        db.commit()
    finally:
        db.close()


def stored_emails():
    db = TestSessionLocal()
    try:
        return sorted(user.email for user in db.query(User).all())
    finally:
        db.close()


def auth_header(value):
    return {"Authorization": value}


# --- password length ----------------------------------------------------------

def test_signup_rejects_7_char_password(client):
    res = client.post("/signup", json={"email": "a@x.com", "password": "1234567"})
    assert res.status_code == 422
    assert stored_emails() == []


def test_signup_accepts_8_char_password(client):
    res = client.post("/signup", json={"email": "a@x.com", "password": "12345678"})
    assert res.status_code == 200


@pytest.mark.parametrize("path", ["/signup", "/login"])
def test_password_over_72_bytes_rejected(client, path):
    res = client.post(path, json={"email": "a@x.com", "password": "a" * 73})
    assert res.status_code == 422


def test_password_of_exactly_72_bytes_accepted(client):
    password = "a" * 72
    assert client.post("/signup", json={"email": "a@x.com", "password": password}).status_code == 200
    assert client.post("/login", json={"email": "a@x.com", "password": password}).status_code == 200


def test_password_limit_counts_utf8_bytes_not_characters(client):
    # "é" is 2 bytes in UTF-8.
    ok = client.post("/signup", json={"email": "a@x.com", "password": "é" * 25})
    assert ok.status_code == 200
    too_long = client.post("/signup", json={"email": "b@x.com", "password": "é" * 37})
    assert too_long.status_code == 422


# --- existing (pre-Step 3) accounts ------------------------------------------

def test_legacy_short_password_can_still_log_in(client):
    seed_user("old@x.com", "abc123")
    res = client.post("/login", json={"email": "old@x.com", "password": "abc123"})
    assert res.status_code == 200


def test_legacy_mixed_case_email_logs_in_case_insensitively(client):
    seed_user("Legacy@X.com", "password123")
    res = client.post("/login", json={"email": "legacy@x.com", "password": "password123"})
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "Legacy@X.com"
    assert decode_access_token(body["token"]) == "Legacy@X.com"


# --- email normalisation ------------------------------------------------------

def test_signup_normalizes_email(client):
    res = client.post("/signup", json={"email": "  User@X.com ", "password": "password123"})
    assert res.status_code == 200
    assert res.json()["email"] == "user@x.com"
    assert decode_access_token(res.json()["token"]) == "user@x.com"
    assert stored_emails() == ["user@x.com"]


def test_login_with_differently_cased_email_after_signup(client):
    client.post("/signup", json={"email": "user@x.com", "password": "password123"})
    res = client.post("/login", json={"email": " USER@X.COM", "password": "password123"})
    assert res.status_code == 200
    assert res.json()["email"] == "user@x.com"


@pytest.mark.parametrize("email", ["no-at-sign", "a@b@c", "@x.com", "a@", "a b@x.com", "", "   "])
@pytest.mark.parametrize("path", ["/signup", "/login"])
def test_invalid_email_rejected(client, path, email):
    res = client.post(path, json={"email": email, "password": "password123"})
    assert res.status_code == 422


def test_email_over_254_chars_rejected(client):
    email = "a" * 245 + "@x.com" + "a" * 4  # 255 characters
    res = client.post("/signup", json={"email": email, "password": "password123"})
    assert res.status_code == 422


# --- duplicate accounts -------------------------------------------------------

def test_signup_duplicate_differing_only_by_case(client):
    assert client.post("/signup", json={"email": "a@x.com", "password": "password123"}).status_code == 200
    res = client.post("/signup", json={"email": "A@X.com", "password": "password123"})
    assert res.status_code == 400
    assert res.json() == {"detail": "Email already registered"}
    assert stored_emails() == ["a@x.com"]


def test_signup_race_integrity_error_returns_400_and_rolls_back(client, monkeypatch):
    seed_user("race@x.com", "password123")
    # Simulate a concurrent signup: the pre-check sees nothing, the insert hits the unique constraint.
    monkeypatch.setattr(app.main, "find_users_by_email", lambda db, email: [])
    res = client.post("/signup", json={"email": "race@x.com", "password": "password123"})
    assert res.status_code == 400
    assert res.json() == {"detail": "Email already registered"}

    monkeypatch.undo()
    follow_up = client.post("/signup", json={"email": "next@x.com", "password": "password123"})
    assert follow_up.status_code == 200
    assert stored_emails() == ["next@x.com", "race@x.com"]


def test_ambiguous_case_variant_accounts_fail_safely_on_login(client, capsys):
    seed_user("Dup@X.com", "first-password")
    seed_user("dup@x.com", "second-password")

    wrong = client.post("/login", json={"email": "dup@x.com", "password": "wrong-password"})
    first = client.post("/login", json={"email": "dup@x.com", "password": "first-password"})
    second = client.post("/login", json={"email": "DUP@x.com", "password": "second-password"})

    for res in (first, second):
        assert res.status_code == 401
        assert res.json() == INVALID_LOGIN == wrong.json()

    log = capsys.readouterr().out
    assert "share a case-insensitive email" in log
    assert "dup@x.com" not in log.lower()


def test_ambiguous_case_variant_accounts_block_new_signup(client):
    seed_user("Dup@X.com", "first-password")
    seed_user("dup@x.com", "second-password")
    res = client.post("/signup", json={"email": "DUP@x.com", "password": "password123"})
    assert res.status_code == 400
    assert stored_emails() == ["Dup@X.com", "dup@x.com"]


# --- chat question ------------------------------------------------------------

def valid_token_header():
    return auth_header(f"Bearer {create_access_token(email='user@x.com')}")


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_empty_question_rejected(client, fake_answer, question):
    res = client.post("/chat", json={"question": question}, headers=valid_token_header())
    assert res.status_code == 422
    assert fake_answer == []


def test_question_over_limit_rejected(client, fake_answer):
    res = client.post("/chat", json={"question": "q" * 1001}, headers=valid_token_header())
    assert res.status_code == 422
    assert fake_answer == []


def test_question_at_limit_accepted(client, fake_answer):
    res = client.post("/chat", json={"question": "q" * 1000}, headers=valid_token_header())
    assert res.status_code == 200
    assert fake_answer == ["q" * 1000]


def test_question_is_stripped_before_answering(client, fake_answer):
    res = client.post("/chat", json={"question": "  hi  "}, headers=valid_token_header())
    assert res.status_code == 200
    assert fake_answer == ["hi"]


# --- Authorization header -----------------------------------------------------

def test_missing_authorization_header_returns_401(client, fake_answer):
    res = client.post("/chat", json={"question": "hi"})
    assert res.status_code == 401
    assert res.json() == {"detail": "Invalid authorization header"}
    assert fake_answer == []


@pytest.mark.parametrize("value", ["Bearer", "Bearer ", "Bearer    "])
def test_bearer_without_token_returns_401(client, fake_answer, value):
    res = client.post("/chat", json={"question": "hi"}, headers=auth_header(value))
    assert res.status_code == 401
    assert res.json() == {"detail": "Invalid authorization header"}
    assert fake_answer == []


def test_lowercase_bearer_scheme_still_rejected(client, fake_answer):
    token = create_access_token(email="user@x.com")
    res = client.post("/chat", json={"question": "hi"}, headers=auth_header(f"bearer {token}"))
    assert res.status_code == 401
    assert fake_answer == []


def test_valid_bearer_token_accepted(client, fake_answer):
    res = client.post("/chat", json={"question": "hi"}, headers=valid_token_header())
    assert res.status_code == 200
    assert fake_answer == ["hi"]
