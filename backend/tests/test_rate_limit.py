"""
Step 8 — rate limiting for /login and /chat.
All offline: see conftest.py. Limiters under test use a fake clock and small limits.
"""

import threading

import pytest

import app.main
from app.auth import create_access_token
from app.rate_limit import RateLimiter, parse_rate_limit
from tests.conftest import run_isolated

RATE_LIMITED = {"detail": "Too many requests. Please try again later."}
PASSWORD = "PASSWORD-MARKER-123"


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def limits(monkeypatch, clock):
    """Swaps the app's limiters for small ones on the fake clock."""
    def _set(chat=(100, 60), login_ip=(100, 60), login_failures=(100, 900)):
        monkeypatch.setattr(app.main, "chat_limiter", RateLimiter(*chat, clock=clock))
        monkeypatch.setattr(app.main, "login_ip_limiter", RateLimiter(*login_ip, clock=clock))
        monkeypatch.setattr(app.main, "login_failure_limiter", RateLimiter(*login_failures, clock=clock))
    return _set


def assert_rate_limited(res, *secrets):
    assert res.status_code == 429
    assert res.json() == RATE_LIMITED
    assert int(res.headers["retry-after"]) >= 1
    for secret in secrets:
        assert secret not in res.text
        assert secret not in str(res.headers)


def login(client, email="user@x.com", password=PASSWORD, **kwargs):
    return client.post("/login", json={"email": email, "password": password}, **kwargs)


def signup(client, email="user@x.com", password=PASSWORD):
    assert client.post("/signup", json={"email": email, "password": password}).status_code == 200


def bearer(email="user@x.com"):
    return {"Authorization": f"Bearer {create_access_token(email=email)}"}


def ask(client, headers, question="hi"):
    return client.post("/chat", json={"question": question}, headers=headers)


# --- RateLimiter --------------------------------------------------------------

def test_allows_up_to_limit_then_blocks(clock):
    limiter = RateLimiter(3, 60, clock=clock)
    assert [limiter.hit("k") for _ in range(3)] == [None, None, None]
    assert limiter.hit("k") == 60


def test_window_slides(clock):
    limiter = RateLimiter(2, 60, clock=clock)
    limiter.hit("k")
    clock.advance(30)
    limiter.hit("k")
    clock.advance(20)
    assert limiter.hit("k") == 10       # first hit leaves the window in 10s
    clock.advance(10)
    assert limiter.hit("k") is None     # it has left; the hit at t+30 is still counted
    assert limiter.hit("k") == 30


def test_blocked_hits_are_not_recorded(clock):
    limiter = RateLimiter(1, 60, clock=clock)
    limiter.hit("k")
    for _ in range(5):
        clock.advance(10)
        limiter.hit("k")
    clock.advance(10)                   # 60s after the only recorded hit
    assert limiter.hit("k") is None


def test_keys_are_independent(clock):
    limiter = RateLimiter(1, 60, clock=clock)
    assert limiter.hit("a") is None
    assert limiter.hit("b") is None
    assert limiter.hit("a") is not None


def test_retry_after_does_not_record_and_record_does_not_check(clock):
    limiter = RateLimiter(2, 60, clock=clock)
    assert limiter.retry_after("k") is None
    limiter.record("k")
    limiter.record("k")
    limiter.record("k")                 # record() never refuses
    assert limiter.retry_after("k") == 60
    assert limiter.retry_after("k") == 60


def test_memory_is_bounded(clock):
    limiter = RateLimiter(5, 60, clock=clock, max_keys=3)
    for key in "abcdef":
        limiter.hit(key)
    assert len(limiter._hits) <= 3


def test_expired_keys_are_cleared_before_evicting_live_ones(clock):
    limiter = RateLimiter(1, 60, clock=clock, max_keys=2)
    limiter.hit("old")
    clock.advance(61)
    limiter.hit("live")
    limiter.hit("new")                  # needs room: "old" has expired, so it goes first
    assert set(limiter._hits) == {"live", "new"}
    assert limiter.hit("live") is not None


def test_concurrent_hits_never_exceed_limit():
    limiter = RateLimiter(50, 60)
    allowed = []
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()
        for _ in range(10):
            if limiter.hit("shared") is None:
                allowed.append(1)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(allowed) == 50


# --- configuration ------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [("20/60", (20, 60)), (" 5 / 900 ", (5, 900)), ("1/1", (1, 1))])
def test_parse_rate_limit(value, expected):
    assert parse_rate_limit(value, "X") == expected


@pytest.mark.parametrize("value", ["", "20", "20/", "/60", "0/60", "20/0", "-1/60", "a/b", "1.5/60"])
def test_parse_rate_limit_rejects_bad_values(value):
    with pytest.raises(RuntimeError, match="X must look like"):
        parse_rate_limit(value, "X")


def test_default_limits():
    from app import config
    assert config.CHAT_RATE_LIMIT == (20, 60)
    assert config.LOGIN_RATE_LIMIT == (10, 60)
    assert config.LOGIN_FAILURE_LIMIT == (5, 900)


def test_limits_configurable_from_environment():
    result = run_isolated(
        "import app.main\n"
        "for name in ('chat_limiter', 'login_ip_limiter', 'login_failure_limiter'):\n"
        "    limiter = getattr(app.main, name)\n"
        "    print('%s=%d/%d' % (name, limiter.limit, limiter.window_seconds))\n",
        env_overrides={"CHAT_RATE_LIMIT": "3/30", "LOGIN_RATE_LIMIT": "4/40", "LOGIN_FAILURE_LIMIT": "2/600"},
    )
    assert result.returncode == 0, result.stderr
    assert "chat_limiter=3/30" in result.stdout
    assert "login_ip_limiter=4/40" in result.stdout
    assert "login_failure_limiter=2/600" in result.stdout


def test_bad_limit_config_fails_at_startup():
    result = run_isolated("import app.config\n", env_overrides={"CHAT_RATE_LIMIT": "lots"})
    assert result.returncode != 0
    assert "CHAT_RATE_LIMIT must look like" in result.stderr


# --- /login: per client IP ----------------------------------------------------

def test_login_below_ip_limit_behaves_normally(client, limits):
    limits(login_ip=(3, 60))
    signup(client)
    assert login(client).status_code == 200
    assert login(client, password="wrong-password").status_code == 401
    assert login(client).status_code == 200


def test_login_over_ip_limit_returns_429_without_echoing_input(client, limits, clock):
    limits(login_ip=(3, 60))
    signup(client, email="victim@x.com")
    for i in range(3):
        assert login(client, email=f"u{i}@x.com").status_code == 401
    res = login(client, email="victim@x.com")   # correct password, but the IP is over its limit
    assert_rate_limited(res, PASSWORD, "victim@x.com")
    assert res.headers["retry-after"] == "60"

    clock.advance(60)
    assert login(client, email="victim@x.com").status_code == 200


def test_login_ip_limit_counts_invalid_requests(client, limits):
    limits(login_ip=(2, 60))
    assert login(client, email="not-an-email").status_code == 422
    assert client.post("/login", json={"email": "a@x.com"}).status_code == 422
    assert_rate_limited(login(client))


def test_login_ip_limit_ignores_forwarded_headers(client, limits):
    """A client can't get a fresh bucket by sending its own X-Forwarded-For."""
    limits(login_ip=(2, 60))
    for i in range(2):
        login(client, headers={"X-Forwarded-For": f"10.0.0.{i}"})
    assert_rate_limited(login(client, headers={"X-Forwarded-For": "10.0.0.99", "X-Real-IP": "10.0.0.98"}))


def test_client_ip_uses_the_direct_peer():
    from types import SimpleNamespace
    assert app.main.client_ip(SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"))) == "203.0.113.7"
    assert app.main.client_ip(SimpleNamespace(client=None)) == "unknown"


# --- /login: failed attempts per email ----------------------------------------

def test_failed_logins_lock_that_email_even_for_the_right_password(client, limits, clock):
    limits(login_failures=(3, 900))
    signup(client)
    for _ in range(3):
        assert login(client, password="wrong-password").status_code == 401
    assert_rate_limited(login(client), PASSWORD, "user@x.com")

    clock.advance(900)
    assert login(client).status_code == 200


def test_failure_limit_is_per_email_and_case_insensitive(client, limits):
    limits(login_failures=(2, 900))
    signup(client, email="a@x.com")
    signup(client, email="b@x.com")
    login(client, email="a@x.com", password="wrong-password")
    login(client, email=" A@X.COM", password="wrong-password")
    assert_rate_limited(login(client, email="a@X.com"))
    assert login(client, email="b@x.com").status_code == 200


def test_unknown_emails_are_limited_the_same_way(client, limits):
    """The response doesn't reveal whether an account exists: unknown emails also hit 429."""
    limits(login_failures=(2, 900))
    for _ in range(2):
        assert login(client, email="ghost@x.com").json() == {"detail": "Invalid email or password"}
    assert_rate_limited(login(client, email="ghost@x.com"))


def test_successful_logins_do_not_count_as_failures(client, limits):
    limits(login_failures=(2, 900))
    signup(client)
    for _ in range(5):
        assert login(client).status_code == 200


def test_ambiguous_case_variant_accounts_count_as_failures(client, limits):
    from tests.test_validation import seed_user
    limits(login_failures=(1, 900))
    seed_user("Dup@X.com", "first-password")
    seed_user("dup@x.com", "second-password")
    assert login(client, email="dup@x.com", password="first-password").status_code == 401
    assert_rate_limited(login(client, email="dup@x.com", password="first-password"))


def test_rate_limit_logs_never_contain_credentials(client, limits, capsys):
    limits(login_failures=(1, 900))
    login(client, email="secret-person@x.com", password="wrong-password")
    login(client, email="secret-person@x.com")
    log = capsys.readouterr().out
    assert "Rate limit exceeded: /login failed attempts per email." in log
    assert "secret-person" not in log and PASSWORD not in log and "testclient" not in log


# --- /chat: per user ----------------------------------------------------------

def test_chat_below_limit_answers(client, limits, fake_answer):
    limits(chat=(3, 60))
    for _ in range(3):
        assert ask(client, bearer()).status_code == 200
    assert fake_answer == ["hi", "hi", "hi"]


def test_chat_over_limit_returns_429_and_skips_the_model(client, limits, fake_answer, clock):
    limits(chat=(2, 60))
    headers = bearer()
    ask(client, headers)
    ask(client, headers)
    res = ask(client, headers, question="QUESTION-MARKER")
    assert_rate_limited(res, "QUESTION-MARKER", headers["Authorization"].split()[1])
    assert fake_answer == ["hi", "hi"]

    clock.advance(60)
    assert ask(client, headers).status_code == 200


def test_chat_limit_is_per_user(client, limits, fake_answer):
    limits(chat=(1, 60))
    assert ask(client, bearer("a@x.com")).status_code == 200
    assert ask(client, bearer("b@x.com")).status_code == 200
    assert ask(client, bearer("a@x.com")).status_code == 429


def test_chat_limit_shared_across_tokens_and_email_case(client, limits, fake_answer):
    limits(chat=(1, 60))
    assert ask(client, bearer("Legacy@X.com")).status_code == 200
    assert ask(client, bearer("legacy@x.com")).status_code == 429


def test_bad_tokens_get_401_and_are_not_counted(client, limits, fake_answer):
    limits(chat=(1, 60))
    for headers in ({}, {"Authorization": "Bearer not-a-jwt"}, {"Authorization": "Token abc"}):
        assert ask(client, headers).status_code == 401
    assert ask(client, bearer()).status_code == 200


def test_invalid_questions_count_toward_the_chat_limit(client, limits, fake_answer):
    """The limiter runs before body validation, so a stream of 422s is limited too."""
    limits(chat=(2, 60))
    headers = bearer()
    assert ask(client, headers, question="   ").status_code == 422
    assert ask(client, headers, question="q" * 1001).status_code == 422
    assert_rate_limited(ask(client, headers))
    assert fake_answer == []


def test_chat_and_login_limits_are_separate(client, limits, fake_answer):
    limits(chat=(1, 60), login_ip=(1, 60))
    signup(client)
    assert login(client).status_code == 200
    assert ask(client, bearer()).status_code == 200
    assert login(client).status_code == 429
    assert ask(client, bearer()).status_code == 429


def test_signup_is_not_rate_limited(client, limits):
    limits(chat=(1, 60), login_ip=(1, 60), login_failures=(1, 900))
    for i in range(5):
        signup(client, email=f"user{i}@x.com")
