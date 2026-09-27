import hmac
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request

from .store import open_store


def create_app(runtime_dir: Path, market_client=None) -> Flask:
    app = Flask(__name__)
    app.config.update(BIND_HOST="127.0.0.1", TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"])
    app.extensions["store"] = open_store(Path(runtime_dir))
    app.extensions["market_client"] = market_client

    @app.before_request
    def guard_writes():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        origin = request.headers.get("Origin", "")
        parsed = urlsplit(origin)
        token = request.headers.get("X-CSRF-Token", "")
        cookie = request.cookies.get("csrf_token", "")
        if (
            request.headers.get("X-App-Request") != "1"
            or not origin
            or parsed.scheme != request.scheme
            or parsed.netloc != request.host
            or not token
            or not cookie
            or not hmac.compare_digest(token, cookie)
        ):
            return jsonify(error="请求来源无效"), 403

    @app.after_request
    def secure_headers(response):
        if not request.cookies.get("csrf_token"):
            response.set_cookie("csrf_token", secrets.token_urlsafe(32), httponly=False, samesite="Strict")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    return app
