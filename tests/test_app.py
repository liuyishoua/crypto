from pathlib import Path

from crypto_app.app import create_app


def test_local_app(tmp_path: Path):
    app = create_app(tmp_path / "run")
    client = app.test_client()

    response = client.get("/health", headers={"Host": "127.0.0.1"})
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    assert app.config["BIND_HOST"] == "127.0.0.1"
    assert (tmp_path / "run" / "crypto.db").exists()
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "wss://mm-sdk-relay.api.cx.metamask.io" in response.headers["Content-Security-Policy"]

    refused = client.post("/api/example", json={}, headers={"Host": "127.0.0.1"})
    assert refused.status_code == 403
