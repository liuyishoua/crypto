# Live Spot Order Book

The market page should expose public, real-time Binance spot depth for the selected symbol. Subscribe in the browser to the official market-data-only WebSocket `wss://data-stream.binance.vision/ws/<symbol>@depth20@1000ms`. This partial-book stream sends complete top-20 snapshots, so no local diff/snapshot reconciliation is needed. Show bids, asks, spread, and the notional-weighted share of resting bid depth. Use exact prices and quantities from the exchange payload; calculate display metrics locally. Label the receipt time and connection state, and clearly separate live depth from the UTC-ended historical chart.

Close the old stream when the selected symbol changes or the market page is hidden. Reconnect after transient disconnects, but never show an old snapshot as live. Treat connection failure as an unavailable live feed. Do not interpret visible limit orders as completed flow or as trader identity; orders may be canceled and the book covers only Binance spot. No trading action is attached to depth rows.

Verify official stream payload and actual browser connectivity, then test symbol switching, disconnection state, and visual layout. Retain a strict CSP with only the market-data WebSocket origin added.
