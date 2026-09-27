# Market Explorer Design

## Purpose

Make spot research navigable without memorizing Binance pairs or typing ISO dates. Users should browse active USDT pairs, adjust chart time and visible range directly, and inspect data-derived signals without mistaking them for proof of large trader activity.

## Market catalog

Use Binance's official `data-api.binance.vision` public market endpoint for exchange information, tickers and recent candles. Cache the exchange catalog and 24-hour snapshot in memory to limit requests. Show active USDT pairs by default, ranked by 24-hour quote volume; search the full spot catalog by base asset or symbol. Preserve last fetched catalog when refresh fails and mark it stale. The UI keeps favorites locally and provides clearly labeled candidate pairs if no catalog has ever loaded. A candidate is not represented as confirmed tradable.

## Chart and date range

Keep Lightweight Charts v5.2.1. Provide 15-minute, 1-hour, 4-hour and 1-day interval buttons; candlestick/line display; fit, zoom and pan. Use a ResizeObserver. Initial dates are computed from UTC today, not hardcoded. Preset ranges and a two-handle draggable range control update the start/end date fields and visible chart range. The end date remains exclusive, and the UI labels that convention. Manual date fields remain available. Loading a new range fetches data; panning and range changes within the loaded data do not trigger a fetch. Backtesting uses the selected date fields and retains its 100-bar minimum. Market viewing can show shorter histories.

## Insights

Derive three time-series from the same validated OHLCV: 20-bar price return, current volume divided by average volume over the preceding 20 bars, and drawdown from the highest close in the last 20 bars. Render responsive, hoverable mini charts with current values and plain-language definitions. Missing warm-up points remain missing. Label these as historical price/volume patterns, not fund flows or identified smart money. Sentiment, exchange flows and wallet attribution require separately sourced data and are outside this release.

## Failure and verification

Catalog and ticker refresh failures must not crash the market page. Distinguish stale data and unverified candidates. Avoid stale asynchronous responses replacing a newer symbol or interval. Tests cover data-source fallback, short viewing ranges, symbol ranking/filtering, and insight calculations; browser verification covers selection, dragging, chart controls and responsive layout. Trading routes and order confirmation behavior remain untouched.
