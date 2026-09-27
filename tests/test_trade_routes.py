from cryptography.fernet import Fernet

from crypto_app.app import create_app
from tests.test_trade_execution import Exchange


class WebExchange(Exchange):
    def permissions(self, key, secret):
        return {"enableReading": True, "enableSpotAndMarginTrading": True, "enableWithdrawals": False}


def request_headers(client):
    client.get("/health")
    return {"Origin": "http://localhost", "X-App-Request": "1", "X-CSRF-Token": client.get_cookie("csrf_token").value}


def test_default_off_csrf_and_real_order_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYPTO_MASTER_KEY", Fernet.generate_key().decode())
    exchange = WebExchange()
    app = create_app(tmp_path, trade_gateway=exchange)
    client = app.test_client()
    headers = request_headers(client)
    intent = {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT", "quantity": "1", "limit_price": "100"}
    assert client.post("/api/trade/previews", json=intent, headers=headers).status_code == 400
    assert client.post("/api/trade/settings", json={"key": "a", "secret": "b", "passphrase": "long unlock phrase", "per_order_limit": "200", "daily_limit": "500"}).status_code == 403
    response = client.post("/api/trade/settings", json={"key": "private-key", "secret": "private-secret", "passphrase": "long unlock phrase", "per_order_limit": "200", "daily_limit": "500"}, headers=headers)
    assert response.status_code == 200
    assert "private-secret" not in response.get_data(as_text=True)
    preview = client.post("/api/trade/previews", json=intent, headers=headers)
    assert preview.status_code == 201
    assert preview.json["estimated_fee"] and preview.json["estimated_slippage"] == "0"
    pid = preview.json["id"]
    assert client.post(f"/api/trade/previews/{pid}/confirm", json={"passphrase": "wrong"}, headers=headers).status_code == 400
    first = client.post(f"/api/trade/previews/{pid}/confirm", json={"passphrase": "long unlock phrase"}, headers=headers)
    second = client.post(f"/api/trade/previews/{pid}/confirm", json={"passphrase": "long unlock phrase"}, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json["client_order_id"] == second.json["client_order_id"]
    assert exchange.sent == 1
    client_id = first.json["client_order_id"]
    assert client.get("/api/trade/orders").json["items"][0]["status"] == "NEW"
    assert client.get(f"/api/trade/orders/{client_id}").json["status"] == "NEW"
    rotation = client.post("/api/trade/settings", json={"key": "different-account", "secret": "private-secret", "passphrase": "long unlock phrase", "per_order_limit": "200", "daily_limit": "500"}, headers=headers)
    assert rotation.status_code == 400
    exchange.status = "PARTIALLY_FILLED"
    assert client.post(f"/api/trade/orders/{client_id}/cancel", json={"passphrase": "long unlock phrase"}, headers=headers).json["status"] == "CANCELED"
    assert "真实币安现货" in client.get("/").get_data(as_text=True)
    assert "预计费用" in client.get("/").get_data(as_text=True)
    assert client.post("/api/trade/settings/disable", json={}, headers=headers).status_code == 200
    assert client.post("/api/trade/previews", json=intent, headers=headers).status_code == 400
