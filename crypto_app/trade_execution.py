import json
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .trade_preview import ManualOrderIntent, OrderPreview, preview_order
from .trade_settings import TradeSettingsStore, verify_unlock


@dataclass(frozen=True)
class LocalOrder:
    client_order_id: str
    preview_id: str
    symbol: str
    side: str
    type: str
    quantity: str
    status: str
    exchange_order_id: str | None
    executed_qty: str
    cancel_requested: bool
    created_at: str


def _intent_json(intent):
    return json.dumps({"symbol": intent.symbol, "side": intent.side, "type": intent.type, "quantity": str(intent.quantity), "limit_price": str(intent.limit_price) if intent.limit_price is not None else None})


def _intent_from_json(value):
    raw = json.loads(value)
    return ManualOrderIntent(raw["symbol"], raw["side"], raw["type"], Decimal(raw["quantity"]), Decimal(raw["limit_price"]) if raw["limit_price"] is not None else None)


class TradeService:
    def __init__(self, db, settings: TradeSettingsStore, gateway):
        self.db = db
        self.settings = settings
        self.gateway = gateway
        self.lock = threading.RLock()
        self.db.execute("CREATE TABLE IF NOT EXISTS trade_previews (id TEXT PRIMARY KEY, intent TEXT NOT NULL, quote TEXT NOT NULL, estimated_notional TEXT NOT NULL, estimated_fee TEXT NOT NULL, estimated_slippage TEXT NOT NULL, expires_at TEXT NOT NULL, rules_snapshot TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS trade_orders (client_order_id TEXT PRIMARY KEY, preview_id TEXT NOT NULL UNIQUE, symbol TEXT NOT NULL, side TEXT NOT NULL, type TEXT NOT NULL, quantity TEXT NOT NULL, estimated_exposure TEXT NOT NULL, status TEXT NOT NULL, exchange_order_id TEXT, executed_qty TEXT NOT NULL DEFAULT '0', cancel_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS trade_audit (id INTEGER PRIMARY KEY, event TEXT NOT NULL, reference TEXT, at TEXT NOT NULL)")
        self.db.commit()

    def audit(self, event, reference=None):
        self.db.execute("INSERT INTO trade_audit(event,reference,at) VALUES(?,?,?)", (event, reference, datetime.now(timezone.utc).isoformat()))
        self.db.commit()

    def _daily_used(self, now):
        day = now.date().isoformat()
        rows = self.db.execute("SELECT estimated_exposure FROM trade_orders WHERE substr(created_at,1,10)=?", (day,)).fetchall()
        return sum((Decimal(row[0]) for row in rows), Decimal(0))

    def preview(self, intent: ManualOrderIntent, now=None) -> OrderPreview:
        now = now or datetime.now(timezone.utc)
        with self.lock:
            result = preview_order(intent, self.gateway, self.settings.load(), now, daily_used=self._daily_used(now))
            self.db.execute("INSERT INTO trade_previews VALUES(?,?,?,?,?,?,?,?)", (result.id, _intent_json(intent), str(result.quote), str(result.estimated_notional), str(result.estimated_fee), str(result.estimated_slippage), result.expires_at.isoformat(), result.rules_snapshot))
            self.db.commit()
            self.audit("preview", result.id)
            return result

    def _unlock(self, passphrase):
        settings = self.settings.load()
        if not settings.enabled or not verify_unlock(passphrase, settings.passphrase_hash):
            raise ValueError("交易未启用或解锁口令错误")
        return settings

    def _order(self, row):
        return LocalOrder(row["client_order_id"], row["preview_id"], row["symbol"], row["side"], row["type"], row["quantity"], row["status"], row["exchange_order_id"], row["executed_qty"], bool(row["cancel_requested"]), row["created_at"])

    def get(self, client_order_id):
        row = self.db.execute("SELECT * FROM trade_orders WHERE client_order_id=?", (client_order_id,)).fetchone()
        if not row:
            raise LookupError("订单不存在")
        return self._order(row)

    def list(self):
        return [self._order(row) for row in self.db.execute("SELECT * FROM trade_orders ORDER BY created_at DESC LIMIT 100").fetchall()]

    def _record_status(self, client_id, payload):
        status = str(payload.get("status", "UNCERTAIN"))
        if status not in ("NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED", "EXPIRED", "PENDING_CANCEL"):
            status = "UNCERTAIN"
        self.db.execute("UPDATE trade_orders SET status=?,exchange_order_id=?,executed_qty=?,updated_at=? WHERE client_order_id=?", (status, str(payload["order_id"]) if payload.get("order_id") is not None else None, str(payload.get("executed_qty", "0")), datetime.now(timezone.utc).isoformat(), client_id))
        self.db.commit()
        self.audit("status:" + status, client_id)
        return self.get(client_id)

    def confirm(self, preview_id: str, passphrase: str, now=None) -> LocalOrder:
        now = now or datetime.now(timezone.utc)
        with self.lock:
            settings = self._unlock(passphrase)
            existing = self.db.execute("SELECT client_order_id FROM trade_orders WHERE preview_id=?", (preview_id,)).fetchone()
            if existing:
                return self.reconcile(existing[0])
            row = self.db.execute("SELECT * FROM trade_previews WHERE id=?", (preview_id,)).fetchone()
            if not row:
                raise LookupError("预览不存在")
            if now >= datetime.fromisoformat(row["expires_at"]):
                raise ValueError("预览已过期，请重新预检")
            intent = _intent_from_json(row["intent"])
            fresh = preview_order(intent, self.gateway, settings, now, daily_used=self._daily_used(now))
            if fresh.rules_snapshot != row["rules_snapshot"] or (intent.type == "MARKET" and abs(fresh.quote - Decimal(row["quote"])) / Decimal(row["quote"]) > Decimal("0.01")):
                raise ValueError("规则或报价变化，请重新预检")
            client_id = "cw" + secrets.token_hex(14)
            stamp = now.isoformat()
            exposure = fresh.estimated_notional + fresh.estimated_slippage + fresh.estimated_fee
            self.db.execute("INSERT INTO trade_orders(client_order_id,preview_id,symbol,side,type,quantity,estimated_exposure,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (client_id, preview_id, intent.symbol, intent.side, intent.type, str(intent.quantity), str(exposure), "UNCERTAIN", stamp, stamp))
            self.db.commit()
            self.audit("submit_attempt", client_id)
            try:
                result = self.gateway.place_order(intent, client_id)
                return self._record_status(client_id, result)
            except Exception:
                return self.reconcile(client_id)

    def reconcile(self, client_order_id: str) -> LocalOrder:
        with self.lock:
            order = self.get(client_order_id)
            try:
                return self._record_status(client_order_id, self.gateway.get_order(order.symbol, client_order_id))
            except Exception:
                return order

    def recover(self):
        for order in self.list():
            if order.status in ("UNCERTAIN", "NEW", "PARTIALLY_FILLED", "PENDING_CANCEL"):
                self.reconcile(order.client_order_id)

    def cancel(self, client_order_id: str, passphrase: str) -> LocalOrder:
        with self.lock:
            self._unlock(passphrase)
            order = self.reconcile(client_order_id)
            if order.status in ("FILLED", "CANCELED", "REJECTED", "EXPIRED") or order.cancel_requested:
                return order
            self.db.execute("UPDATE trade_orders SET cancel_requested=1 WHERE client_order_id=?", (client_order_id,))
            self.db.commit()
            self.audit("cancel_attempt", client_order_id)
            try:
                return self._record_status(client_order_id, self.gateway.cancel_order(order.symbol, client_order_id))
            except Exception:
                return self.reconcile(client_order_id)
