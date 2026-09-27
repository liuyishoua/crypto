# 币安现货真实手动交易 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为个人工作台加入币安现货真实手动订单，逐笔预检、预览、解锁确认并查询交易所状态。

**Architecture:** `OrderIntent` 与研究模块共享数据形状，但策略和回测不持有真实执行器引用。真实交易服务由手动 HTTP 路由调用，先持久化唯一 `clientOrderId` 再发送一次；不确定状态只查询。交易默认关闭，凭证、限额和解锁均在服务端验证。

**Tech Stack:** Python 3.12、Flask、SQLite、cryptography、Binance 官方 Python SDK、pytest；自动测试全用假交易所适配器。

**Spec:** `docs/superpowers/specs/2026-09-27-spot-research-workbench-design.md`

## Global Constraints

- 本计划在 `2026-09-27-market-research.md` 和 `2026-09-27-assets.md` 完成后执行。
- 真实交易默认关闭；交易密钥与只读密钥分离，提现权限必须拒绝。
- 只允许手动限价/市价买卖与取消；策略、回测、后台任务不得发送真实订单。
- 真实接口只在本机监听，写请求需同源/CSRF；每次提交和取消需解锁口令。
- 自动测试不得调用币安真实下单；真实联调只由所有者逐笔确认。

## Review Focus

- 重复 HTTP 确认与浏览器重试：同一预览只产生一个 `clientOrderId`，至多发送一次（Task 3）。
- 币安超时或 5xx 后实际可能成交：只查询原订单，不重新提交（Task 3）。
- 过滤规则或余额在预览后变化：确认时重新校验并拒绝过期预览（Task 2/3）。
- 市价单金额无法精确预估：报价、费用和滑点标为估计，仍受限额约束（Task 2/4）。
- 部分成交订单被取消或进程中断：交易所状态优先，启动后恢复查询（Task 3/4）。

---

### Task 1: 交易设置和凭证隔离

**Files:** Create `crypto_app/trade_settings.py`, `tests/test_trade_settings.py`；modify `crypto_app/secrets.py`, `crypto_app/app.py`.

**Interfaces:** `TradeSettings(enabled, per_order_limit, daily_limit, passphrase_hash)`；`configure_trade(settings, key_permissions, passphrase) -> None`；`verify_unlock(passphrase, stored_hash) -> bool`。正数限额和带盐口令哈希均由服务端保存。

- [ ] **Step 1: Write the failing test:** 默认禁用；无主密钥、无口令、非正数限额或提现权限均拒绝启用；只读和交易凭证互不覆盖；错误口令不泄露凭证。
- [ ] **Step 2: Run test to verify it fails:** `pytest tests/test_trade_settings.py -v`，预期模块缺失。
- [ ] **Step 3: Implement:** 交易密钥独立加密槽位，权限检查、限额持久化、口令哈希与启停审计。
- [ ] **Step 4: Run test to verify it passes:** `pytest tests/test_trade_settings.py -v`。
- [ ] **Step 5: Commit:** `git add crypto_app tests/test_trade_settings.py && git commit -m "feat: guard live trading settings"`。

### Task 2: 订单预检与预览

**Files:** Create `crypto_app/trade_preview.py`, `tests/test_trade_preview.py`；modify `crypto_app/app.py`.

**Interfaces:** `preview_order(intent: ManualOrderIntent, exchange: ExchangeGateway, settings: TradeSettings, now: datetime) -> OrderPreview`；`ManualOrderIntent(symbol, side, type, quantity, limit_price)`；`OrderPreview(id, intent, quote, estimated_fee, estimated_slippage, expires_at, rules_snapshot)`。

- [ ] **Step 1: Write the failing test:** 假交易所覆盖 `exchangeInfo` 状态、价格/数量步进、最小和最大名义金额、可用余额、单笔/当日限额；测试订单失败不生成可确认预览；费用与滑点标为估计。
- [ ] **Step 2: Run test to verify it fails:** `pytest tests/test_trade_preview.py -v`，预期预检接口缺失。
- [ ] **Step 3: Implement:** 实时规则、余额、报价查询；服务端调用币安测试下单接口；短有效期预览入库，并记录审计摘要而非密钥。
- [ ] **Step 4: Run test to verify it passes:** `pytest tests/test_trade_preview.py -v`。
- [ ] **Step 5: Commit:** `git add crypto_app tests/test_trade_preview.py && git commit -m "feat: preflight live spot orders"`。

### Task 3: 幂等提交、核实与取消

**Files:** Create `crypto_app/trade_execution.py`, `tests/test_trade_execution.py`；modify `crypto_app/app.py`.

**Interfaces:** `confirm_order(preview_id: str, passphrase: str, gateway: ExchangeGateway) -> LocalOrder`；`reconcile_order(client_order_id: str, gateway: ExchangeGateway) -> LocalOrder`；`cancel_order(client_order_id: str, passphrase: str, gateway: ExchangeGateway) -> LocalOrder`。`ExchangeGateway` 包含测试下单、真实下单、按 client ID 查询和取消。

- [ ] **Step 1: Write the failing test:** 确认前重新校验过期/规则/余额/限额；持久化 ID 后重复确认至多一次发送；超时、5xx、进程重启均查询原 ID；部分成交、成交、取消、拒绝按交易所状态更新；取消必须再验口令。
- [ ] **Step 2: Run test to verify it fails:** `pytest tests/test_trade_execution.py -v`，预期执行接口缺失。
- [ ] **Step 3: Implement:** SQLite 唯一约束和事务、先写“准备提交”后发送、未知状态不重试提交、启动恢复只读核实、优雅关闭时排空在途写操作。
- [ ] **Step 4: Run test to verify it passes:** `pytest tests/test_trade_execution.py -v`。
- [ ] **Step 5: Commit:** `git add crypto_app tests/test_trade_execution.py && git commit -m "feat: execute manual orders once and reconcile"`。

### Task 4: 真实交易界面与端到端保护

**Files:** Create `tests/test_trade_routes.py`；modify `crypto_app/app.py`, `crypto_app/static/app.js`, `crypto_app/static/style.css`, `crypto_app/templates/index.html`, `README.md`.

**Interfaces:** `POST /api/trade/previews`、`POST /api/trade/previews/<id>/confirm`、`GET /api/trade/orders`、`GET /api/trade/orders/<id>`、`POST /api/trade/orders/<id>/cancel`。路由仅接受手动表单，研究模块无执行路由。

- [ ] **Step 1: Write the failing test:** HTTP 级验证未启用、跨站、缺口令、重复确认、部分成交与取消；页面始终标出“真实币安现货”，预览显示数量、方向、订单类型、估算金额/费用/滑点/限额，提交请求与成交状态分别呈现。
- [ ] **Step 2: Run test to verify it fails:** `pytest tests/test_trade_routes.py -v`，预期路由缺失。
- [ ] **Step 3: Implement:** 本地交易表单、预览弹窗、二次确认与订单状态页；禁用自动交易入口；README 说明只在本机使用、密钥权限和停用步骤。
- [ ] **Step 4: Run test to verify it passes:** `pytest tests/test_trade_routes.py -v && pytest -q`；在假交易所下人工查看桌面与窄屏。
- [ ] **Step 5: Commit:** `git add crypto_app README.md tests/test_trade_routes.py && git commit -m "feat: add guarded manual spot trading UI"`。
