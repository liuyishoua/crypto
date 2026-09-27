# Live Order Book Plan

1. Verify Binance spot depth documentation and a live REST snapshot to confirm the depth shape.
2. Add a market-page order book with stream status, top bids/asks, spread, and 20-level resting notional balance.
3. Connect and disconnect the public depth WebSocket according to the selected symbol and page visibility, with bounded reconnect attempts and stale-state handling.
4. Use one REST request for recent chart ranges of up to 1000 bars, and show chart loading state immediately.
5. Add CSP coverage, README notes, run the full suite, inspect in a browser, and publish the verified branch.
