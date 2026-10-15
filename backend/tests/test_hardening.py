"""
Final hardening — JWTs must carry `exp`, and 422 responses must not echo submitted input.
All offline: see conftest.py.
"""

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from jose import JWTError, jwt

from app.auth import ALGORITHM, create_access_token, decode_access_token
from app.config import JWT_SECRET

EMAIL = "user@x.com"


def b64url(data):
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def signed(claims, secret=JWT_SECRET, algorithm=ALGORITHM):
    return jwt.encode(claims, secret, algorithm=algorithm)


def future(days=1):
    return datetime.now(timezone.utc) + timedelta(days=days)


def chat(client, token):
    return client.post("/chat", json={"question": "hi"}, headers={"Authorization": f"Bearer {token}"})


# --- JWT: exp is required -----------------------------------------------------

def test_token_without_exp_is_rejected(client, fake_answer):
    token = signed({"sub": EMAIL})  # correct secret and algorithm, but no expiry
    with pytest.raises(JWTError):
        decode_access_token(token)
    res = chat(client, token)
    assert res.status_code == 401
    assert res.json() == {"detail": "Invalid or expired token"}
    assert fake_answer == []


def test_issued_tokens_carry_exp_and_still_work(client, fake_answer):
    token = create_access_token(email=EMAIL)
    claims = jwt.get_unverified_claims(token)
    assert isinstance(claims["exp"], int)
    assert decode_access_token(token) == EMAIL
    assert chat(client, token).status_code == 200


def test_valid_token_with_exp_accepted(client, fake_answer):
    res = chat(client, signed({"sub": EMAIL, "exp": future()}))
    assert res.status_code == 200
    assert fake_answer == ["hi"]


def tampered_token():
    header, _, signature = signed({"sub": EMAIL, "exp": future()}).split(".")
    return f"{header}.{b64url({'sub': 'admin@x.com', 'exp': int(future(30).timestamp())})}.{signature}"


@pytest.mark.parametrize(
    "make_token",
    [
        lambda: signed({"sub": EMAIL, "exp": datetime.now(timezone.utc) - timedelta(seconds=5)}),
        tampered_token,
        lambda: signed({"sub": EMAIL, "exp": future()}, secret="not-the-secret"),
        lambda: signed({"sub": EMAIL, "exp": future()}, algorithm="HS512"),
        lambda: f"{b64url({'alg': 'none', 'typ': 'JWT'})}.{b64url({'sub': EMAIL, 'exp': int(future().timestamp())})}.",
        lambda: signed({"exp": future()}),
        lambda: "not-a-jwt",
        lambda: "a.b.c",
    ],
    ids=["expired", "tampered", "wrong-secret", "wrong-algorithm", "alg-none", "missing-sub", "garbage", "malformed"],
)
def test_bad_tokens_still_rejected(client, fake_answer, make_token):
    res = chat(client, make_token())
    assert res.status_code == 401
    assert res.json() == {"detail": "Invalid or expired token"}
    assert fake_answer == []


# --- 422: no submitted input in the response ----------------------------------

def assert_sanitized(res, *secrets):
    assert res.status_code == 422
    body = res.json()
    assert isinstance(body["detail"], list) and body["detail"]
    for error in body["detail"]:
        assert set(error) == {"type", "loc", "msg"}  # no "input", no "ctx", no "url"
        assert isinstance(error["msg"], str) and error["msg"]
        assert isinstance(error["loc"], list)
    for secret in secrets:
        assert secret not in res.text
    return body["detail"]


def test_short_signup_password_not_echoed(client):
    detail = assert_sanitized(
        client.post("/signup", json={"email": "a@x.com", "password": "Sh0rt!x"}), "Sh0rt!x"
    )
    assert detail == [
        {"type": "value_error", "loc": ["body", "password"], "msg": "Value error, Password must be at least 8 characters"}
    ]


@pytest.mark.parametrize("path", ["/signup", "/login"])
def test_overlong_password_not_echoed(client, path):
    password = "SECRET-PASSWORD-MARKER-" + "x" * 60
    assert_sanitized(client.post(path, json={"email": "a@x.com", "password": password}), password, "SECRET-PASSWORD-MARKER")


def test_invalid_email_and_password_not_echoed(client):
    detail = assert_sanitized(
        client.post("/signup", json={"email": "EMAIL-MARKER-no-at-sign", "password": "PW-MK"}),  # 5 chars: too short
        "EMAIL-MARKER", "PW-MK",
    )
    assert {tuple(error["loc"]) for error in detail} == {("body", "email"), ("body", "password")}


def test_missing_field_reports_location_without_echoing_body(client):
    detail = assert_sanitized(client.post("/login", json={"email": "BODY-MARKER@x.com"}), "BODY-MARKER")
    assert detail == [{"type": "missing", "loc": ["body", "password"], "msg": "Field required"}]


def test_wrong_type_not_echoed(client):
    assert_sanitized(client.post("/login", json={"email": "a@x.com", "password": {"nested": "TYPE-MARKER"}}), "TYPE-MARKER")


def test_malformed_json_body_not_echoed(client):
    raw = '{"email": "a@x.com", "password": "RAW-BODY-MARKER"'  # truncated JSON
    res = client.post("/signup", content=raw, headers={"Content-Type": "application/json"})
    detail = assert_sanitized(res, "RAW-BODY-MARKER")
    assert detail[0]["type"] == "json_invalid"


def test_overlong_question_not_echoed(client, fake_answer):
    question = "QUESTION-MARKER " + "q" * 1000
    res = client.post(
        "/chat", json={"question": question}, headers={"Authorization": f"Bearer {create_access_token(email=EMAIL)}"}
    )
    assert_sanitized(res, "QUESTION-MARKER")
    assert fake_answer == []


def test_valid_requests_unaffected(client):
    res = client.post("/signup", json={"email": "ok@x.com", "password": "password123"})
    assert res.status_code == 200
    assert set(res.json()) == {"token", "email"}
