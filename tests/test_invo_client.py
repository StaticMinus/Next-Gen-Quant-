"""Contract tests for the Invo REST client (no network, no credentials).

These lock the request shapes to the reverse-engineered API documented in
invo-copy-trader-master/README.md and mirrored in src/invo-client.ts.
"""

import base64
import json

import pytest

from src.integrations import invo_ctrader_copier as mod


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def make_jwt(expires_in_seconds: int = 86400) -> str:
    header = b64url(json.dumps({"alg": "none"}).encode())
    exp = 9999999999 if expires_in_seconds > 0 else 1
    payload = b64url(json.dumps({"expires": exp}).encode())
    return f"{header}.{payload}.sig"


class FakeResponse:
    def __init__(self, status=200, payload=None, text=None, raise_on_json=False):
        self.status_code = status
        self._payload = payload
        self._raise = raise_on_json
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._raise:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, get_responses=None, post_responses=None):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.gets = []
        self.posts = []

    def get(self, url, headers=None, timeout=None):
        self.gets.append((url, headers or {}))
        return self.get_responses.pop(0)

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append((url, headers or {}, json))
        return self.post_responses.pop(0)


def client_with(session, refresh_token="REFRESH_JWT"):
    client = mod.InvoClient(refresh_token=refresh_token)
    client.session = session
    return client


def test_missing_refresh_token_fails_loudly():
    client = mod.InvoClient(refresh_token="")
    client.refresh_token = ""
    with pytest.raises(RuntimeError, match="INVO_REFRESH_TOKEN"):
        client.ensure_token()


def test_refresh_then_authorized_request_sends_required_headers():
    access = make_jwt()
    session = FakeSession(
        get_responses=[FakeResponse(200, {"accessToken": access})],
        post_responses=[FakeResponse(200, {"items": [{"id": "post-1"}]})],
    )

    items = client_with(session).get_feed("following", item_limit=20)

    assert items == [{"id": "post-1"}]
    refresh_url, refresh_headers = session.gets[0]
    assert refresh_url.endswith("/v1_0/auth/refresh_token")
    assert refresh_headers["Authorization"] == "Bearer REFRESH_JWT"

    post_url, post_headers, body = session.posts[0]
    assert post_url.endswith("/v1_0/posts/get_feed")
    assert post_headers["Authorization"] == f"Bearer {access}"
    assert post_headers["Content-Type"] == "application/json"
    assert post_headers["x-app-version"] == "0.0.75"
    assert post_headers["x-platform"] == "web"
    assert body == {
        "filter": {"filter": "following", "assetTypes": []},
        "params": {"lastPostId": None, "itemLimit": 20},
    }


def test_expired_access_token_is_refreshed_before_use():
    session = FakeSession(
        get_responses=[FakeResponse(200, {"accessToken": make_jwt()})],
        post_responses=[FakeResponse(200, {"items": []})],
    )
    client = client_with(session)
    expired = make_jwt(expires_in_seconds=-1)
    client.token = expired

    client.get_feed("following")

    assert len(session.gets) == 1
    assert session.posts[0][1]["Authorization"] != f"Bearer {expired}"
    assert session.posts[0][1]["Authorization"].startswith("Bearer ")


def test_401_triggers_one_refresh_and_retry():
    fresh = make_jwt()
    session = FakeSession(
        get_responses=[
            FakeResponse(200, {"accessToken": make_jwt()}),
            FakeResponse(200, {"accessToken": fresh}),
        ],
        post_responses=[
            FakeResponse(401, {"error": "expired"}),
            FakeResponse(200, {"items": [{"id": "retried"}]}),
        ],
    )

    items = client_with(session).get_feed("following")

    assert items == [{"id": "retried"}]
    assert len(session.gets) == 2
    assert len(session.posts) == 2
    assert session.posts[1][1]["Authorization"] == f"Bearer {fresh}"


def test_base64_encoded_response_body_is_decoded():
    access = make_jwt()
    payload = {"items": [{"id": "b64"}]}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    session = FakeSession(
        get_responses=[FakeResponse(200, {"accessToken": access})],
        post_responses=[FakeResponse(200, None, text=encoded, raise_on_json=True)],
    )

    assert client_with(session).get_feed("following") == [{"id": "b64"}]


def test_http_error_raises_with_body():
    session = FakeSession(
        get_responses=[FakeResponse(200, {"accessToken": make_jwt()})],
        post_responses=[FakeResponse(403, {"message": "forbidden"})],
    )
    with pytest.raises(RuntimeError, match="403"):
        client_with(session).get_feed("following")


def test_discover_payload_matches_documented_contract():
    session = FakeSession(
        get_responses=[FakeResponse(200, {"accessToken": make_jwt()})],
        post_responses=[FakeResponse(200, {"items": [{"portfolioId": "x"}]})],
    )

    traders = client_with(session).discover_traders(page=2, size=50)

    assert traders == [{"portfolioId": "x"}]
    url, _, body = session.posts[0]
    assert url.endswith("/v1_0/trending/get_portfolios_pl")
    assert body == {"filter": "trending", "params": {"page": 2, "size": 50}}


def test_follow_payload_uses_object_id():
    session = FakeSession(
        get_responses=[FakeResponse(200, {"accessToken": make_jwt()})],
        post_responses=[FakeResponse(200, {"ok": True})],
    )

    client_with(session).follow_user("user-42")

    url, _, body = session.posts[0]
    assert url.endswith("/v1_0/users/follow")
    assert body == {"objectId": "user-42"}


def test_feed_returns_empty_list_on_unexpected_shape():
    session = FakeSession(
        get_responses=[FakeResponse(200, {"accessToken": make_jwt()})],
        post_responses=[FakeResponse(200, {"unexpected": True})],
    )
    assert client_with(session).get_feed("following") == []


# -- token persistence ------------------------------------------------------ #


def test_write_env_value_replaces_empty_placeholder(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nINVO_REFRESH_TOKEN=\nB=2\n", encoding="utf-8")

    mod.write_env_value(env, "INVO_REFRESH_TOKEN", "JWT123")

    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines == ["A=1", "INVO_REFRESH_TOKEN=JWT123", "B=2"]


def test_write_env_value_appends_when_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")

    mod.write_env_value(env, "INVO_REFRESH_TOKEN", "JWT123")

    assert env.read_text(encoding="utf-8").splitlines() == ["A=1", "INVO_REFRESH_TOKEN=JWT123"]


def test_set_refresh_token_rejects_non_jwt(tmp_path, capsys):
    env = tmp_path / ".env"
    assert mod.set_refresh_token("not-a-jwt", env_path=env) == 1
    assert "not a JWT" in capsys.readouterr().out
    assert not env.exists()


def test_set_refresh_token_rejects_expired(tmp_path, capsys):
    env = tmp_path / ".env"
    assert mod.set_refresh_token(make_jwt(expires_in_seconds=-1), env_path=env) == 1
    assert "expired" in capsys.readouterr().out


class StubInvoClient:
    def __init__(self, posts=None, error=None):
        self.posts = posts or []
        self.error = error
        self.refresh_token = ""
        self.token = ""

    def ensure_token(self):
        if self.error:
            raise RuntimeError(self.error)
        self.token = "access"

    def get_feed(self, filter_name, item_limit=20):
        return self.posts


def test_set_refresh_token_persists_valid_token(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("INVO_REFRESH_TOKEN=\n", encoding="utf-8")
    token = make_jwt()

    code = mod.set_refresh_token(token, env_path=env, client=StubInvoClient(posts=[{"id": "p"}]))

    assert code == 0
    assert env.read_text(encoding="utf-8").strip() == f"INVO_REFRESH_TOKEN={token}"
    out = capsys.readouterr().out
    assert "saved INVO_REFRESH_TOKEN" in out and "1 post" in out


def test_set_refresh_token_does_not_persist_rejected_token(tmp_path):
    env = tmp_path / ".env"
    env.write_text("INVO_REFRESH_TOKEN=\n", encoding="utf-8")

    code = mod.set_refresh_token(make_jwt(), env_path=env,
                                 client=StubInvoClient(error="401 unauthorized"))

    assert code == 1
    assert env.read_text(encoding="utf-8").strip() == "INVO_REFRESH_TOKEN="
