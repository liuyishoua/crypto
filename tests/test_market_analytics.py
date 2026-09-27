import os
import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("swift"), reason="JavaScriptCore smoke test requires Swift")
def test_depth_and_executed_flow_are_distinct():
    source = Path(__file__).parents[1] / "crypto_app/static/market_analytics.js"
    script = f'''import Foundation
import JavaScriptCore
let context = JSContext()!
context.evaluateScript(try! String(contentsOfFile: "{source}", encoding: .utf8))
let depth = context.evaluateScript(#"JSON.stringify(MarketAnalytics.depth([["100","2"],["99","1"]], [["101","1"],["102","2"]], 2))"#)!.toString()!
let flow = context.evaluateScript(#"JSON.stringify(MarketAnalytics.flow([{{price:100,quantity:2,buyerMaker:false,time:1000}},{{price:101,quantity:1,buyerMaker:true,time:1000}},{{price:99,quantity:9,buyerMaker:false,time:0}}], 500))"#)!.toString()!
let candle = context.evaluateScript(#"JSON.stringify(MarketAnalytics.candle({{t:3600000,o:'100',h:'105',l:'99',c:'103',v:'7',x:false}}))"#)!.toString()!
print(depth)
print(flow)
print(candle)
'''
    env = os.environ.copy()
    env["SWIFT_MODULE_CACHE_PATH"] = "/private/tmp/crypto-swift-cache"
    env["CLANG_MODULE_CACHE_PATH"] = "/private/tmp/crypto-clang-cache"
    result = subprocess.run(["swift", "-e", script], text=True, capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    depth, flow, candle = [json.loads(line) for line in result.stdout.splitlines()]
    assert depth["bidNotional"] == 299
    assert depth["askNotional"] == 305
    assert depth["buyShare"] == pytest.approx(299 / 604 * 100)
    assert flow["buyNotional"] == 200
    assert flow["sellNotional"] == 101
    assert flow["buyShare"] == pytest.approx(200 / 301 * 100)
    assert flow["count"] == 2
    assert candle == {"time": 3600, "open": 100, "high": 105, "low": 99, "close": 103, "volume": "7", "isOpen": True}
