import os
import signal
import threading
from pathlib import Path

from werkzeug.serving import make_server

from .app import create_app


if __name__ == "__main__":
    app = create_app(Path(os.environ.get("CRYPTO_RUNTIME_DIR", ".runtime")))
    server = make_server("127.0.0.1", 8765, app, threaded=True)
    server.daemon_threads = False

    def stop(_signal, _frame):
        app.extensions["draining"].set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        trade = app.extensions["trade_service"]
        if trade is not None:
            with trade.lock:
                pass
