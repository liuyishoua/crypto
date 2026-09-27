# Market Explorer Implementation Plan

**Goal:** Add a browseable spot market and adjustable research charts.

**Architecture:** Extend the existing public market adapter and `/api/symbols` and `/api/candles` routes. Keep insight math in a small Python module; keep browser interaction in the existing market page script and styles.

**Tech Stack:** Flask, requests, pytest, vanilla JavaScript, Lightweight Charts 5.2.1.

**Spec:** `docs/superpowers/specs/2026-09-27-market-explorer-design.md`

## Tasks

- [ ] Test and implement Binance public-data endpoint, cached catalog/tickers, active USDT ranking and stale fallback.
- [ ] Test and implement viewable short candle ranges and server-calculated price/volume insight series.
- [ ] Add market list, favorites and search with stale/unverified labeling; verify live API behavior.
- [ ] Add chart controls, date presets, draggable range control and hoverable insight charts; verify browser interactions.
- [ ] Run Python suite, static checks and browser QA; inspect the final diff and integrate the branch.
