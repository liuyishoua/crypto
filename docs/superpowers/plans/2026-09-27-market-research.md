# 现货市场与策略回测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在独立本机工作台中搜索币安现货交易对、检验历史 K 线、记录公开策略，并运行可解释的现货回测。

**Architecture:** Flask 只负责本机 HTTP 和页面，`market` 负责数据来源与校验，`strategy` 只生成意图，`backtest` 独立记账。SQLite 保存来源、笔记、数据版本及运行结果；前端使用本项目自己的静态资源。

**Tech Stack:** Python 3.12、Flask、SQLite、pytest、Binance 公共 REST/历史数据、Lightweight Charts；统计可用 `bt`，成交账本不得交给 `bt`。

**Spec:** `docs/superpowers/specs/2026-09-27-spot-research-workbench-design.md`

## Global Constraints

- 项目位于 `/Users/leo/leo-project/crypto/`，与 `DouYin_Spider/` 同级，独立运行。
- 默认仅绑定 `127.0.0.1`；`.runtime/`、`.env` 和凭证不得进入 Git。
- 首版只做现货、单交易对、无借贷、无做空回测；统一 UTC。
- 信号使用已收盘 K 线，最早下一根开盘模拟成交；手续费和滑点入账。
- 不执行网页复制的 Python 代码；回测绝不调用真实交易接口。

## Review Focus

- 交易对刚上市不足 100 根 K 线：拒绝运行并解释覆盖不足（Task 2/4）。
- 重复、缺口、逆序及零/负价 K 线：拒绝而非修补（Task 2）。
- 参数为零、负数或超大窗口：表单和策略层都拒绝（Task 3）。
- 模拟资金不足或卖出超过持币：不得产生负余额（Task 4）。
- 网络断开或限流：显示缓存时间和错误，不冒充实时数据（Task 2/5）。

---

### Task 1: 本机应用与数据目录

**Files:** Create `pyproject.toml`, `README.md`, `crypto_app/app.py`, `crypto_app/store.py`, `crypto_app/__main__.py`, `tests/test_app.py`.

**Interfaces:** `create_app(runtime_dir: Path, market_client=None) -> Flask`；`open_store(runtime_dir: Path) -> sqlite3.Connection`。后续模块由 `create_app` 装配，不从页面直接写数据库。

- [ ] **Step 1: Write the failing test:** `test_local_app` 断言 `/health` 返回 JSON、写请求无同源标记返回 403、默认运行配置 host 为 `127.0.0.1`，运行数据只落在临时目录。
- [ ] **Step 2: Run test to verify it fails:** `pytest tests/test_app.py -v`，预期缺少 `crypto_app.app`。
- [ ] **Step 3: Implement:** 上述签名；入口从环境读取运行目录，设置可信 Host、同源与 CSRF 校验、错误响应及安全响应头；README 写本机启动方法。
- [ ] **Step 4: Run test to verify it passes:** `pytest tests/test_app.py -v`。
- [ ] **Step 5: Commit:** `git add pyproject.toml README.md crypto_app tests/test_app.py && git commit -m "feat: bootstrap local crypto workbench"`。

### Task 2: 交易对和 K 线数据

**Files:** Create `crypto_app/market.py`, `crypto_app/binance_public.py`, `tests/test_market.py`；modify `crypto_app/app.py`.

**Interfaces:** `Candle(open_at, open, high, low, close, volume)` 使用 UTC 时间和 Decimal 数值；`MarketData(exchange, market_type, symbol, interval, candles, source, fetched_at, checksum)`；`validate_candles(data: MarketData, min_bars: int = 100) -> None`；`BinancePublicClient.symbols(query: str) -> list[SymbolInfo]`、`candles(symbol, interval, start, end) -> MarketData`。`SymbolInfo` 包含 base、quote、状态和活跃度字段。

- [ ] **Step 1: Write the failing test:** 固定响应中搜索主流币和山寨币；测试缺口、重复、逆序、异常 OHLC、短于 100 根；CSV 缺字段/时区被拒；网络错误时返回带缓存时间的状态，不伪称实时。
- [ ] **Step 2: Run test to verify it fails:** `pytest tests/test_market.py -v`，预期模块缺失。
- [ ] **Step 3: Implement:** 公共接口与数据校验；币安公开归档用于批量历史 K 线，公共 REST 用于交易对目录和近期数据；历史数据按交易所/市场类型/交易对/粒度/区间缓存并记录来源、校验与获取时间；CSV 导入显式要求列映射、交易对和 UTC 时区，走同一验证入口。
- [ ] **Step 4: Run test to verify it passes:** `pytest tests/test_market.py -v`。
- [ ] **Step 5: Commit:** `git add crypto_app tests/test_market.py && git commit -m "feat: validate and cache spot market data"`。

### Task 3: 公开策略规则与研究笔记

**Files:** Create `crypto_app/strategy.py`, `crypto_app/research.py`, `tests/test_strategy.py`.

**Interfaces:** `OrderIntent(signal_at, symbol, side, fraction, reason)`；`StrategySpec(kind, parameters, version, source_url, note)`；`generate_intents(spec: StrategySpec, candles: Sequence[Candle]) -> list[OrderIntent]`；`save_research(store, spec) -> int`。

- [ ] **Step 1: Write the failing test:** 均线交叉、区间突破、定投和买入持有各有固定输入/期望信号；参数非法被拒；来源链接和笔记可保存，但任何输入字符串不作为代码执行。
- [ ] **Step 2: Run test to verify it fails:** `pytest tests/test_strategy.py -v`，预期模块缺失。
- [ ] **Step 3: Implement:** 四种内建规则，只读取信号时刻及之前的已收盘 K 线；策略版本和自然语言说明随记录保存。
- [ ] **Step 4: Run test to verify it passes:** `pytest tests/test_strategy.py -v`。
- [ ] **Step 5: Commit:** `git add crypto_app tests/test_strategy.py && git commit -m "feat: add explainable spot strategies"`。

### Task 4: 下一根 K 线成交与结果账本

**Files:** Create `crypto_app/backtest.py`, `tests/test_backtest.py`.

**Interfaces:** `run_backtest(data: MarketData, spec: StrategySpec, initial_cash: Decimal, fee_rate: Decimal, slippage_rate: Decimal) -> BacktestResult`；结果包含逐笔信号与成交、现金和币余额、收益、最大回撤、胜率、费用、基准与数据版本。

- [ ] **Step 1: Write the failing test:** 固定 100+ 根 K 线证明信号收盘后下一根开盘成交、手续费/滑点计算、资金和持币不为负、最后一根未成交信号不补单；短于 30 天不显示年化，异常数据拒绝；保存结果后能读回数据、参数和策略版本。
- [ ] **Step 2: Run test to verify it fails:** `pytest tests/test_backtest.py -v`，预期缺少执行器。
- [ ] **Step 3: Implement:** 单交易对现货账本，按 Decimal 记账；保存数据版本、参数、费用假设、策略版本；买入持有同区间比较；OHLC 成交限制随结果返回。
- [ ] **Step 4: Run test to verify it passes:** `pytest tests/test_backtest.py -v`。
- [ ] **Step 5: Commit:** `git add crypto_app/backtest.py tests/test_backtest.py && git commit -m "feat: add deterministic spot backtests"`。

### Task 5: 市场、策略和回测页面

**Files:** Create `crypto_app/static/style.css`, `crypto_app/static/app.js`, `crypto_app/templates/index.html`, `tests/test_research_routes.py`；modify `crypto_app/app.py`, `README.md`.

**Interfaces:** `GET /api/symbols`、`GET /api/candles`、`POST /api/research`、`POST /api/backtests`、`GET /api/backtests/<id>`；页面导航预留资产、交易和设置，但未实现的区域说明状态。

- [ ] **Step 1: Write the failing test:** HTTP 级验证搜索、数据覆盖、策略来源保存、回测结果及错误提示；页面含行情图容器、模拟标签、数据来源与更新时间。
- [ ] **Step 2: Run test to verify it fails:** `pytest tests/test_research_routes.py -v`，预期路由缺失。
- [ ] **Step 3: Implement:** 参考 `../DouYin_Spider/web/static/style.css` 的浅色侧栏、顶栏、面板、表格和弹窗节奏，样式独立；图表有信号/模拟成交标记及 TradingView 署名，窄屏可用。
- [ ] **Step 4: Run test to verify it passes:** `pytest tests/test_research_routes.py -v && pytest -q`；人工查看桌面和窄屏。
- [ ] **Step 5: Commit:** `git add crypto_app README.md tests/test_research_routes.py && git commit -m "feat: add market research workbench UI"`。
