import pytest
from fastapi.testclient import TestClient

from nodewright import oidc
from nodewright.config import Settings
from nodewright.main import create_app

H = {"X-Nodewright": "1"}


class FakeProvider(oidc.Provider):
    """authentik stand-in: any code is accepted and maps to the subject
    recorded for it."""

    def __init__(self, settings):
        super().__init__(settings)
        self.subjects: dict[str, str] = {}

    def metadata(self):
        return {"authorization_endpoint": "https://auth.example/authorize"}

    def exchange(self, code, verifier, redirect_uri):
        if code not in self.subjects:
            raise oidc.SignInRefused("bad code")
        return {"id_token": code}

    def verify(self, id_token, nonce):
        sub = self.subjects[id_token]
        return {"iss": self.settings.oidc_issuer, "sub": sub, "preferred_username": sub}


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path}/t.db", public_url="http://testserver",
                    oidc_issuer="https://auth.example/app/", oidc_client_id="nw",
                    oidc_client_secret="s", max_canvas_bytes=20_000, dev_login=True)


@pytest.fixture
def app_and_provider(settings):
    provider = FakeProvider(settings)
    return create_app(settings, provider), provider


def sign_in(app, provider, sub: str) -> TestClient:
    client = TestClient(app)
    r = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 302
    state = r.headers["location"].split("state=")[1].split("&")[0]
    provider.subjects["code-" + sub] = sub
    r = client.get(f"/api/auth/oidc/callback?code=code-{sub}&state={state}",
                   follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/"
    return client


@pytest.fixture
def client(app_and_provider):
    app, provider = app_and_provider
    return sign_in(app, provider, "alice")
