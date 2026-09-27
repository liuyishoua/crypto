import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("swift"), reason="JavaScriptCore smoke test requires Swift")
def test_market_time_and_book_reading():
    source = Path(__file__).parents[1] / "crypto_app/static/market_presentation.js"
    script = f'''import Foundation
import JavaScriptCore
let context = JSContext()!
context.evaluateScript(try! String(contentsOfFile: "{source}", encoding: .utf8))
let result = context.evaluateScript(#"JSON.stringify({{time: MarketPresentation.dualTime(Date.parse('2026-09-26T23:30:00Z')), daily: MarketPresentation.chartTime(Date.parse('2026-09-26T23:30:00Z') / 1000, '1d'), intraday: MarketPresentation.chartTime(Date.parse('2026-09-26T23:30:00Z') / 1000, '1h'), mixed: MarketPresentation.bookReading(70, 30, 20, 60), few: MarketPresentation.bookReading(70, 80, 1, 60), short: MarketPresentation.bookReading(70, 80, 20, 3), move: MarketPresentation.priceMove([{{time: 1000, price: '100'}}, {{time: 2000, price: '101'}}]), noMove: MarketPresentation.priceMove([{{time: 1000, price: '100'}}])}})"#)!.toString()!
print(result)
'''
    env = os.environ.copy()
    env["SWIFT_MODULE_CACHE_PATH"] = "/private/tmp/crypto-swift-cache"
    env["CLANG_MODULE_CACHE_PATH"] = "/private/tmp/crypto-clang-cache"
    result = subprocess.run(["swift", "-e", script], text=True, capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["time"] == "2026-09-27 07:30:00 北京时间 (UTC+8) · 2026-09-26 23:30:00 UTC"
    assert data["daily"] == "09-27"
    assert data["intraday"] == "07:30"
    assert "挂单偏买" in data["mixed"]["headline"] and "成交偏卖" in data["mixed"]["headline"]
    assert "撤销" in data["mixed"]["detail"]
    assert "样本不足" in data["few"]["headline"]
    assert "样本不足" in data["short"]["headline"]
    assert data["move"] == pytest.approx(1)
    assert data["noMove"] is None
