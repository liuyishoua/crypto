from crypto_app.app import create_app
from crypto_app.strategy_sources import StrategySourceCatalog, SourceUnavailable


class Response:
    def raise_for_status(self): pass
    def json(self):
        return {"sha": "a" * 40, "truncated": False, "tree": [
            {"path": "user_data/strategies/Beta.py", "type": "blob", "sha": "b" * 40},
            {"path": "user_data/strategies/Alpha.py", "type": "blob", "sha": "c" * 40},
            {"path": "user_data/strategies/author/Nested.py", "type": "blob", "sha": "f" * 40},
            {"path": "user_data/strategies/README.md", "type": "blob", "sha": "d" * 40},
            {"path": "other/Evil.py", "type": "blob", "sha": "e" * 40},
        ]}


class Session:
    def __init__(self): self.calls = 0; self.fail = False
    def get(self, url, **kwargs):
        self.calls += 1
        if self.fail: raise OSError("offline")
        assert url == "https://api.github.com/repos/freqtrade/freqtrade-strategies/git/trees/main?recursive=1"
        return Response()


def test_catalog_lists_immutable_external_sources_and_uses_cache():
    session = Session()
    catalog = StrategySourceCatalog(session=session)
    first = catalog.sources()
    assert [item["name"] for item in first["items"]] == ["Alpha", "author/Nested", "Beta"]
    assert first["items"][0]["url"] == f"https://github.com/freqtrade/freqtrade-strategies/blob/{'a' * 40}/user_data/strategies/Alpha.py"
    assert first["items"][0]["license"] == "GPL-3.0"
    assert first["daily"] in first["items"]
    assert catalog.sources() == first
    assert session.calls == 1
    catalog._fetched_at = None
    session.fail = True
    assert catalog.sources()["stale"] is True


def test_catalog_failure_without_cache_is_explicit():
    session = Session(); session.fail = True
    try: StrategySourceCatalog(session=session).sources()
    except SourceUnavailable: pass
    else: assert False, "expected source error"


def test_source_routes_save_notes_separately_from_native_backtests(tmp_path):
    app = create_app(tmp_path, strategy_catalog=StrategySourceCatalog(session=Session()))
    app.testing = True
    browser = app.test_client()
    browser.get("/health")
    csrf = browser.get_cookie("csrf_token").value
    headers = {"Host": "localhost", "Origin": "http://localhost", "X-App-Request": "1", "X-CSRF-Token": csrf}
    sources = browser.get("/api/strategy-sources")
    assert sources.status_code == 200
    item = sources.json["items"][0]
    saved = browser.post("/api/strategy-notes", headers=headers, json={"path": item["path"], "revision": item["revision"], "note": "先理解入场，再考虑回测"})
    assert saved.status_code == 201
    notes = browser.get("/api/strategy-notes")
    assert notes.json["items"][0]["path"] == item["path"]
    assert notes.json["items"][0]["revision"] == item["revision"]
    assert browser.post("/api/strategy-notes", headers=headers, json={"path": "../bad.py", "revision": item["revision"], "note": "x"}).status_code == 400
    assert browser.post("/api/strategy-notes", headers=headers, json={"path": "user_data/strategies/../bad.py", "revision": item["revision"], "note": "x"}).status_code == 400
    assert browser.post("/api/strategy-notes", headers=headers, json={"path": item["path"], "revision": "bad", "note": "x"}).status_code == 400
    app.extensions["strategy_catalog"] = StrategySourceCatalog(session=Session())
    app.extensions["strategy_catalog"].session.fail = True
    assert browser.post("/api/strategy-notes", headers=headers, json={"path": item["path"], "revision": item["revision"], "note": "离线时保留已选固定版本"}).status_code == 201
