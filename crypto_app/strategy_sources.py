from datetime import datetime, timedelta, timezone

import requests


class SourceUnavailable(Exception):
    pass


class StrategySourceCatalog:
    TREE_URL = "https://api.github.com/repos/freqtrade/freqtrade-strategies/git/trees/main?recursive=1"
    PATH_PREFIX = "user_data/strategies/"

    def __init__(self, session=None):
        self.session = session or requests.Session()
        self._items = []
        self._fetched_at = None
        self.stale = False

    def sources(self):
        now = datetime.now(timezone.utc)
        if self._fetched_at is None or now - self._fetched_at > timedelta(hours=6):
            try:
                response = self.session.get(self.TREE_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "crypto-workbench"}, timeout=10)
                response.raise_for_status()
                tree = response.json()
                revision = tree["sha"]
                if tree.get("truncated") or len(revision) != 40:
                    raise ValueError("策略目录不完整")
                items = []
                for row in tree["tree"]:
                    path = row["path"]
                    if row["type"] != "blob" or not path.startswith(self.PATH_PREFIX) or not path.endswith(".py"):
                        continue
                    items.append({"name": path[len(self.PATH_PREFIX):-3], "path": path, "revision": revision, "file_sha": row["sha"], "license": "GPL-3.0", "engine": "freqtrade", "url": f"https://github.com/freqtrade/freqtrade-strategies/blob/{revision}/{path}"})
                if not items:
                    raise ValueError("策略目录为空")
                self._items = sorted(items, key=lambda item: item["name"].casefold())
                self._fetched_at = now
                self.stale = False
            except Exception as exc:
                if not self._items:
                    raise SourceUnavailable("公开策略目录暂不可用，请稍后重试") from exc
                self.stale = True
                self._fetched_at = now - timedelta(hours=5, minutes=59)
        daily = self._items[now.date().toordinal() % len(self._items)]
        return {"items": self._items, "daily": daily, "stale": self.stale, "fetched_at": self._fetched_at.isoformat()}
