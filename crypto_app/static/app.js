const $ = (id) => document.getElementById(id);
const state = { chart: null, series: null, volumeSeries: null, candles: [], liveBar: null, liveBarOpen: false, chartSymbol: null, chartInterval: null, chartLiveMode: false, insights: [], fills: [], rangeDays: [], chartStyle: 'candle', marketRequestId: 0, symbolRequestId: 0, symbols: [], favorites: [], marketTab: 'all', chartResizeObserver: null, syncingRange: false, insightVisible: [], insightRangeKey: null, insightTimer: null, marketSymbol: null, orderBookSocket: null, orderBookSymbol: null, orderBookInterval: null, orderBookGeneration: 0, orderBookReconnect: null, orderBookStaleTimer: null, orderBookAttempts: 0, bookHistory: [], recentTrades: [], tapeRenderTimer: null, strategySources: [], selectedStrategySource: null, strategySourcesLoaded: false };

function csrf() {
  const item = document.cookie.split('; ').find((part) => part.startsWith('csrf_token='));
  return item ? decodeURIComponent(item.split('=')[1]) : '';
}

async function api(path, options = {}) {
  const method = options.method || 'GET';
  const headers = method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-App-Request': '1', 'X-CSRF-Token': csrf() };
  const response = await fetch(path, { ...options, headers: { ...headers, ...(options.headers || {}) } });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || '请求失败');
  return body;
}

function toast(message) {
  const element = $('toast');
  element.textContent = message;
  element.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove('show'), 4500);
}

function query() {
  return new URLSearchParams({ symbol: $('symbol').value.trim().toUpperCase(), interval: $('interval').value, start: $('start').value, end: $('end').value });
}

function showPage(name) {
  if (name !== 'market') stopOrderBook('已暂停 · 返回市场页后恢复');
  document.querySelectorAll('.page').forEach((page) => page.classList.toggle('active', page.id === `page-${name}`));
  document.querySelectorAll('.navlink').forEach((button) => button.classList.toggle('active', button.dataset.page === name));
  const titles = { market: '研究 / 现货市场', strategy: '研究 / 策略实验室', records: '研究 / 回测记录', assets: '账户 / 资产总览', trade: '交易 / 真实币安现货', settings: '账户 / 连接与风控' };
  $('topbar-title').textContent = titles[name];
  $('topbar-mode').textContent = name === 'trade' ? '● 真实交易 · 逐笔确认' : name === 'assets' || name === 'settings' ? '● 本机账户 · 只读默认' : '● 研究模式 · 模拟结果';
  $('topbar-mode').classList.toggle('live-mode', name === 'trade');
  if (name === 'records') loadRecords();
  if (name === 'strategy' && !state.strategySourcesLoaded) loadStrategySources();
  if (name === 'market') {
    if (state.chart) state.chart.applyOptions({ width: $('chart').clientWidth, height: $('chart').clientHeight });
    if (state.marketSymbol) startOrderBook(state.marketSymbol);
  }
  if (name === 'assets') loadAssets();
  if (name === 'trade') { loadTradeSettings(); loadTradeOrders(); }
}

let tradeDialogAction = null;
function formatOrderStatus(status) {
  return ({ NEW: '已提交 · 待成交', PARTIALLY_FILLED: '部分成交', FILLED: '已成交', CANCELED: '已取消', REJECTED: '已拒绝', EXPIRED: '已过期', UNCERTAIN: '待核实', PENDING_CANCEL: '取消处理中' })[status] || status;
}
async function loadTradeSettings() {
  try {
    const data = await api('/api/trade/settings');
    $('trade-enabled').textContent = data.enabled ? `已启用 · 单笔 ${data.per_order_limit} USDT · 单日 ${data.daily_limit} USDT` : '真实交易已关闭';
    $('trade-preview').disabled = !data.enabled;
  } catch (error) { $('trade-enabled').textContent = error.message; $('trade-preview').disabled = true; }
}
async function configureTrade() {
  try {
    const data = { key: $('trade-key').value.trim(), secret: $('trade-secret').value, passphrase: $('trade-passphrase').value, per_order_limit: $('trade-per-limit').value, daily_limit: $('trade-day-limit').value };
    await api('/api/trade/settings', { method: 'POST', body: JSON.stringify(data) });
    $('trade-key').value = ''; $('trade-secret').value = ''; $('trade-passphrase').value = '';
    await loadTradeSettings(); toast('真实交易已启用。每笔订单仍需预检与解锁。');
  } catch (error) { toast(error.message); }
}
async function disableTrade() {
  try { await api('/api/trade/settings/disable', { method: 'POST', body: '{}' }); await loadTradeSettings(); toast('真实交易已关闭。'); }
  catch (error) { toast(error.message); }
}
function showTradeDialog(title, lines, button, action) {
  $('trade-dialog-title').textContent = title;
  $('trade-dialog-summary').replaceChildren(...lines.map(([label, value]) => { const row = document.createElement('div'); const name = document.createElement('span'); name.textContent = label; const detail = document.createElement('strong'); detail.textContent = String(value); row.append(name, detail); return row; }));
  $('trade-dialog-submit').textContent = button;
  $('trade-unlock').value = '';
  tradeDialogAction = action;
  $('trade-dialog').showModal();
}
async function previewTrade() {
  try {
    const body = { symbol: $('trade-symbol').value.trim().toUpperCase(), side: $('trade-side').value, type: $('trade-type').value, quantity: $('trade-quantity').value, limit_price: $('trade-type').value === 'LIMIT' ? $('trade-limit-price').value : null };
    const preview = await api('/api/trade/previews', { method: 'POST', body: JSON.stringify(body) });
    showTradeDialog('真实币安现货订单预览', [['交易对', preview.symbol], ['方向', preview.side === 'BUY' ? '买入' : '卖出'], ['类型', preview.type === 'MARKET' ? '市价' : '限价'], ['数量', preview.quantity], ['报价 / 限价', preview.quote], ['预计金额', `${preview.estimated_notional} USDT`], ['预计费用', `${preview.estimated_fee} USDT`], ['预计滑点', `${preview.estimated_slippage} USDT`], ['单笔上限', `${preview.per_order_limit} USDT`], ['单日上限', `${preview.daily_limit} USDT`], ['预览有效至', new Date(preview.expires_at).toLocaleString()]], '确认真实下单', async (passphrase) => {
      const order = await api(`/api/trade/previews/${preview.id}/confirm`, { method: 'POST', body: JSON.stringify({ passphrase }) });
      toast(`提交请求已处理；订单状态：${formatOrderStatus(order.status)}。`);
      await loadTradeOrders();
    });
  } catch (error) { toast(error.message); }
}
async function loadTradeOrders() {
  try {
    const data = await api('/api/trade/orders');
    $('trade-orders').replaceChildren(...data.items.map((item) => {
      const row = document.createElement('tr');
      assetCell(row, [new Date(item.created_at).toLocaleString(), item.symbol, `${item.side === 'BUY' ? '买入' : '卖出'} / ${item.type === 'MARKET' ? '市价' : '限价'}`, item.quantity, formatOrderStatus(item.status), item.executed_qty]);
      const cell = document.createElement('td'); const check = document.createElement('button'); check.textContent = '核实'; check.addEventListener('click', async () => { try { const detail = await api(`/api/trade/orders/${item.client_order_id}`); toast(`${detail.symbol}：${formatOrderStatus(detail.status)}，已成交 ${detail.executed_qty}`); await loadTradeOrders(); } catch (error) { toast(error.message); } }); cell.append(check);
      if (!['FILLED', 'CANCELED', 'REJECTED', 'EXPIRED'].includes(item.status) && !item.cancel_requested) {
        const cancel = document.createElement('button'); cancel.textContent = '取消'; cancel.addEventListener('click', () => showTradeDialog('取消真实订单', [['交易对', item.symbol], ['当前状态', formatOrderStatus(item.status)], ['客户端订单 ID', item.client_order_id]], '解锁并请求取消', async (passphrase) => { const order = await api(`/api/trade/orders/${item.client_order_id}/cancel`, { method: 'POST', body: JSON.stringify({ passphrase }) }); toast(`取消请求已处理；订单状态：${formatOrderStatus(order.status)}。`); await loadTradeOrders(); })); cell.append(cancel);
      }
      row.append(cell); return row;
    }));
    if (!data.items.length) { const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = 7; cell.textContent = '暂无真实订单。'; row.append(cell); $('trade-orders').append(row); }
  } catch (error) { const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = 7; cell.textContent = error.message; row.append(cell); $('trade-orders').replaceChildren(row); }
}
async function submitTradeDialog() {
  const passphrase = $('trade-unlock').value;
  if (!passphrase) { toast('请输入交易解锁口令。'); return; }
  $('trade-dialog-submit').disabled = true;
  try { await tradeDialogAction(passphrase); $('trade-dialog').close(); }
  catch (error) { toast(error.message); }
  finally { $('trade-unlock').value = ''; $('trade-dialog-submit').disabled = false; }
}

let assetRequest = 0;
function assetCell(row, values) {
  values.forEach((value) => { const cell = document.createElement('td'); cell.textContent = value == null ? '—' : String(value); row.append(cell); });
}
function renderAssetRows(target, items, onchain) {
  $(target).replaceChildren(...items.map((item) => {
    const row = document.createElement('tr');
    const source = item.price_source ? `${item.price_source} · ${new Date(item.price_at).toLocaleString()}` : '未计价';
    const values = onchain ? [`${item.chain_id === 1 ? 'Ethereum' : 'BNB Smart Chain'} / ${item.symbol}`, item.contract || '原生币', item.quantity, item.value_usd ?? '未计价', source, new Date(item.observed_at).toLocaleString()] : [item.symbol, item.quantity, item.value_usd ?? '未计价', source, new Date(item.observed_at).toLocaleString()];
    assetCell(row, values); return row;
  }));
  if (!items.length) { const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = onchain ? 6 : 5; cell.textContent = '暂无资产数据'; row.append(cell); $(target).append(row); }
}
function clearAssets() {
  $('binance-assets').replaceChildren(); $('onchain-assets').replaceChildren();
  $('asset-total').textContent = '—'; $('asset-unpriced').textContent = '—';
  $('asset-notices').replaceChildren(); $('asset-status').textContent = '加载中';
}
async function loadAssets() {
  const requestId = ++assetRequest;
  clearAssets();
  try {
    const address = $('wallet-address').value.trim();
    const data = await api(`/api/assets${address ? `?address=${encodeURIComponent(address)}` : ''}`);
    if (requestId !== assetRequest) return;
    $('asset-total').textContent = data.total_usd;
    $('asset-unpriced').textContent = String(data.unpriced_count);
    $('asset-status').textContent = data.groups['binance-spot'].length || data.groups.onchain.length ? '已更新' : '暂无资产';
    $('asset-updated').textContent = new Date().toLocaleString();
    renderAssetRows('binance-assets', data.groups['binance-spot'], false);
    renderAssetRows('onchain-assets', data.groups.onchain, true);
    const notices = Object.entries(data.errors).map(([source, message]) => `${message}。上次成功 ${data.last_success[source] ? new Date(data.last_success[source]).toLocaleString() : '未知'}`);
    Object.entries(data.discovery).forEach(([chain, status]) => { if (!status.complete) notices.push(`${chain === '1' ? 'Ethereum' : 'BNB Smart Chain'} 资产发现不完整：${status.error || '索引器暂不可用'}；已知余额仍显示。上次完整发现 ${data.last_success[chain] ? new Date(data.last_success[chain]).toLocaleString() : '未知'}`); });
    $('asset-notices').replaceChildren(...notices.map((message) => { const element = document.createElement('p'); element.className = 'asset-notice'; element.textContent = message; return element; }));
  } catch (error) { if (requestId === assetRequest) { $('asset-status').textContent = '查询失败'; toast(error.message); } }
}

async function connectWallet() {
  try {
    if (!window.cryptoWallet) throw new Error('MetaMask Connect 尚未加载');
    $('wallet-address').value = await window.cryptoWallet.selectAddress();
    await loadAssets();
  } catch (error) { toast(error.message); }
}

async function connectReadKey() {
  try {
    await api('/api/binance/read-credentials', { method: 'POST', body: JSON.stringify({ key: $('read-key').value.trim(), secret: $('read-secret').value }) });
    $('read-key').value = ''; $('read-secret').value = '';
    toast('币安只读账户已连接。');
  } catch (error) { toast(error.message); }
}

const intervalSeconds = { '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400 };
const utcDate = (value) => new Date(value).toISOString().slice(0, 10);
const dayTimestamp = (value) => Date.parse(`${value}T00:00:00Z`) / 1000;
const addUtcDays = (value, days) => utcDate(Date.parse(`${value}T00:00:00Z`) + days * 86400000);

function setPreset(days, load = true) {
  const allowed = Math.max(1, Math.floor(2500 * intervalSeconds[$('interval').value] / 86400));
  const actual = Math.min(days, allowed);
  const end = addUtcDays(utcDate(new Date()), 1);
  $('end').value = end;
  $('start').value = addUtcDays(end, -actual);
  document.querySelectorAll('[data-days]').forEach((button) => button.classList.toggle('active', Number(button.dataset.days) === days));
  if (actual !== days) toast(`当前周期最多加载约 ${allowed} 天，已缩短日期范围。`);
  if (load) loadMarket();
}

function updateSelectedPair(symbol) {
  const quote = ['USDT', 'BTC', 'ETH', 'BNB'].find((suffix) => symbol.endsWith(suffix)) || '';
  $('selected-pair').textContent = quote ? `${symbol.slice(0, -quote.length)} / ${quote}` : symbol;
  $('symbol-hint').textContent = '选择左侧币种，或展开“自定义日期”输入交易对';
}

function renderChart(candles, fills = [], preserveRange = false) {
  const container = $('chart');
  if (!window.LightweightCharts) { container.textContent = '图表组件暂不可用，请查看下方数据。'; return; }
  const previousRange = preserveRange && state.chart ? state.chart.timeScale().getVisibleRange() : null;
  state.chartResizeObserver?.disconnect();
  if (state.chart) state.chart.remove();
  const chart = LightweightCharts.createChart(container, { width: container.clientWidth, height: container.clientHeight, layout: { background: { color: '#ffffff' }, textColor: '#667085' }, grid: { vertLines: { color: '#f3f5f8' }, horzLines: { color: '#f3f5f8' } }, rightPriceScale: { borderColor: '#e8ebf0' }, timeScale: { borderColor: '#e8ebf0', timeVisible: $('interval').value !== '1d' }, handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true }, handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true } });
  const series = state.chartStyle === 'line' ? chart.addSeries(LightweightCharts.LineSeries, { color: '#347fe8', lineWidth: 2 }) : chart.addSeries(LightweightCharts.CandlestickSeries, { upColor: '#249e81', downColor: '#df6a6a', borderVisible: false, wickUpColor: '#249e81', wickDownColor: '#df6a6a' });
  series.setData(candles.map(({ time, open, high, low, close }) => state.chartStyle === 'line' ? { time, value: close } : { time, open, high, low, close }));
  const volume = chart.addSeries(LightweightCharts.HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '', lastValueVisible: false, priceLineVisible: false });
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
  volume.setData(candles.map(({ time, open, close, volume: amount }) => ({ time, value: Number(amount), color: close >= open ? '#a7dccc' : '#f3b3b3' })));
  if (state.liveBar && state.liveBar.time >= candles.at(-1).time) {
    const bar = state.liveBar;
    series.update(state.chartStyle === 'line' ? { time: bar.time, value: bar.close } : { time: bar.time, open: bar.open, high: bar.high, low: bar.low, close: bar.close });
    volume.update({ time: bar.time, value: Number(bar.volume), color: bar.close >= bar.open ? '#a7dccc' : '#f3b3b3' });
  }
  const markers = fills.map((fill) => ({ time: Math.floor(Date.parse(fill.filled_at) / 1000), position: fill.side === 'BUY' ? 'belowBar' : 'aboveBar', color: fill.side === 'BUY' ? '#249e81' : '#df6a6a', shape: fill.side === 'BUY' ? 'arrowUp' : 'arrowDown', text: `${fill.side === 'BUY' ? '模拟买入' : '模拟卖出'} ${Number(fill.price).toFixed(3)}` }));
  if (markers.length) LightweightCharts.createSeriesMarkers(series, markers);
  chart.timeScale().fitContent();
  if (previousRange) chart.timeScale().setVisibleRange(previousRange);
  chart.subscribeCrosshairMove((point) => {
    const bar = state.liveBar?.time === point.time ? state.liveBar : candles.find((item) => item.time === point.time);
    if (!bar) return;
    const isOpen = state.liveBar?.time === bar.time && state.liveBarOpen;
    $('ohlc-readout').textContent = `${new Date(bar.time * 1000).toLocaleString()}（本机）${isOpen ? ' · 未收盘' : ''}  开 ${bar.open}  高 ${bar.high}  低 ${bar.low}  收 ${bar.close}  量 ${Number(bar.volume).toLocaleString()}`;
    const index = state.insightVisible.findIndex((item) => item.time === bar.time);
    if (index >= 0) updateInsightHover(index);
  });
  chart.timeScale().subscribeVisibleTimeRangeChange((range) => {
    if (!range || state.syncingRange || !state.rangeDays.length || typeof range.from !== 'number') return;
    const first = state.rangeDays.findIndex((day, index) => index === state.rangeDays.length - 1 || dayTimestamp(state.rangeDays[index + 1]) > range.from);
    const last = state.rangeDays.findIndex((day) => dayTimestamp(day) > range.to);
    $('range-start').value = String(Math.max(0, first));
    $('range-end').value = String(Math.max(Number($('range-start').value) + 1, last === -1 ? state.rangeDays.length : last));
    syncRangeLabels();
  });
  state.chartResizeObserver = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth, height: container.clientHeight }));
  state.chartResizeObserver.observe(container);
  state.chart = chart;
  state.series = series;
  state.volumeSeries = volume;
  state.fills = fills;
}

function clearOrderBook(status) {
  $('order-book-status').textContent = status;
  $('book-best').textContent = '—';
  $('book-spread').textContent = '—';
  $('book-balance').textContent = '—';
  $('book-balance-5').textContent = '—';
  $('book-balance-change').textContent = '—';
  $('book-trend').setAttribute('d', '');
  $('book-trend-range').textContent = '等待数据';
  state.bookHistory = [];
  $('book-received').textContent = '—';
  $('book-bids').textContent = '等待数据';
  $('book-asks').textContent = '等待数据';
}

function stopOrderBook(status = '已暂停') {
  ++state.orderBookGeneration;
  clearTimeout(state.orderBookReconnect);
  clearTimeout(state.orderBookStaleTimer);
  clearTimeout(state.tapeRenderTimer);
  state.orderBookReconnect = null;
  state.orderBookStaleTimer = null;
  const socket = state.orderBookSocket;
  state.orderBookSocket = null;
  state.orderBookSymbol = null;
  state.orderBookInterval = null;
  state.recentTrades = [];
  state.tapeRenderTimer = null;
  $('tape-buy-share').textContent = '—';
  $('recent-trades').textContent = '等待成交';
  state.orderBookAttempts = 0;
  if (socket) socket.close();
  clearOrderBook(status);
}

function orderBookActive() {
  return !document.hidden && $('page-market').classList.contains('active');
}

function bookPrice(value) {
  const [whole, decimals = ''] = String(value).split('.');
  return `${Number(whole).toLocaleString()}${decimals.replace(/0+$/, '') ? `.${decimals.replace(/0+$/, '')}` : ''}`;
}

function bookAmount(value) {
  const number = Number(value);
  return number >= 1e6 ? `${(number / 1e6).toFixed(2)}M` : number >= 1e3 ? `${(number / 1e3).toFixed(2)}K` : number.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function renderBookLevels(target, levels, side, receivedAt, updateId) {
  const maxNotional = Math.max(1, ...levels.map(([price, quantity]) => Number(price) * Number(quantity)));
  let cumulative = 0;
  const received = new Date(receivedAt);
  const shortTime = received.toLocaleTimeString(undefined, { hour12: false, fractionalSecondDigits: 3 });
  const rows = levels.map(([price, quantity]) => {
    const notional = Number(price) * Number(quantity);
    cumulative += notional;
    const row = document.createElement('div');
    row.className = `book-level ${side}`;
    row.title = `币安现货 ${side === 'bid' ? '买盘' : '卖盘'}价位（汇总）\n价格：${price}\n数量：${quantity}\n该档名义金额：${notional}\n前 ${levels.length} 档内累计到此：${cumulative}\n本机接收：${received.toLocaleString()}\nUTC：${received.toISOString()}\n盘口更新 ID：${updateId}\n公开接口不提供挂单账号和单笔挂单时间`;
    const width = Math.max(1, Math.min(100, notional / maxNotional * 100));
    row.style.background = `linear-gradient(to left, ${side === 'bid' ? '#e7f5ef' : '#fff0ef'} ${width}%, transparent ${width}%)`;
    for (const value of [bookPrice(price), bookAmount(quantity), bookAmount(cumulative), shortTime]) {
      const cell = document.createElement('span'); cell.textContent = value; row.append(cell);
    }
    return row;
  });
  $(target).replaceChildren(...rows);
}

function renderOrderBook(snapshot) {
  const bids = snapshot.bids.slice(0, 20), asks = snapshot.asks.slice(0, 20);
  if (!bids.length || !asks.length) { clearOrderBook('盘口暂无挂单'); return; }
  if (![...bids, ...asks].every((level) => Array.isArray(level) && Number(level[0]) > 0 && Number(level[1]) >= 0 && Number.isFinite(Number(level[0]) * Number(level[1])))) { clearOrderBook('盘口数据异常'); return; }
  const bidPrice = Number(bids[0][0]), askPrice = Number(asks[0][0]);
  if (!(bidPrice > 0 && askPrice >= bidPrice)) { clearOrderBook('盘口数据异常'); return; }
  const top5 = MarketAnalytics.depth(bids, asks, 5);
  const top20 = MarketAnalytics.depth(bids, asks, 20);
  const receivedAt = Date.now();
  $('book-best').textContent = `${bookPrice(bids[0][0])} / ${bookPrice(asks[0][0])}`;
  $('book-spread').textContent = `${bookPrice((askPrice - bidPrice).toFixed(8))} · ${((askPrice - bidPrice) / askPrice * 100).toFixed(4)}%`;
  $('book-balance-5').textContent = top5.buyShare === null ? '—' : `${top5.buyShare.toFixed(1)}%`;
  $('book-balance').textContent = top20.buyShare === null ? '—' : `${top20.buyShare.toFixed(1)}%`;
  if (top20.buyShare !== null) {
    state.bookHistory.push({ time: receivedAt, share: top20.buyShare });
    state.bookHistory = state.bookHistory.filter((point) => point.time >= receivedAt - 60000);
    const first = state.bookHistory[0];
    const change = top20.buyShare - first.share;
    $('book-balance-change').textContent = `${change >= 0 ? '+' : ''}${change.toFixed(1)} 个百分点 · ${Math.round((receivedAt - first.time) / 1000)} 秒`;
    const shares = state.bookHistory.map((point) => point.share);
    const low = Math.max(0, Math.min(...shares) - 2);
    const high = Math.min(100, Math.max(...shares) + 2);
    const span = Math.max(8, high - low);
    const center = (low + high) / 2;
    const min = Math.max(0, Math.min(100 - span, center - span / 2));
    const max = min + span;
    $('book-trend-range').textContent = `纵轴 ${min.toFixed(1)}–${max.toFixed(1)}% · 横轴最近 60 秒`;
    $('book-trend').setAttribute('d', state.bookHistory.map((point, index) => `${index ? 'L' : 'M'} ${(600 - (receivedAt - point.time) / 100).toFixed(1)} ${(64 - (point.share - min) / (max - min) * 56).toFixed(1)}`).join(' '));
  }
  $('book-received').textContent = new Date(receivedAt).toLocaleString();
  $('order-book-status').textContent = '● 实时连接中';
  renderBookLevels('book-bids', bids, 'bid', receivedAt, snapshot.lastUpdateId);
  renderBookLevels('book-asks', asks, 'ask', receivedAt, snapshot.lastUpdateId);
}

function renderTradeTape() {
  state.tapeRenderTimer = null;
  state.recentTrades = state.recentTrades.filter((trade) => trade.time >= Date.now() - 60000);
  const flow = MarketAnalytics.flow(state.recentTrades, Date.now() - 60000);
  $('tape-buy-share').textContent = flow.buyShare === null ? '等待成交' : `${flow.buyShare.toFixed(1)}% · ${flow.count} 条`;
  const rows = state.recentTrades.slice(-12).reverse().map((trade) => {
    const row = document.createElement('div');
    row.className = 'recent-trade';
    const time = new Date(trade.time);
    row.title = `币安现货成交 ID：${trade.id}\n交易所成交时间：${time.toLocaleString()}\nUTC：${time.toISOString()}\n价格：${trade.price}\n数量：${trade.quantity}\n名义成交额：${Number(trade.price) * Number(trade.quantity)}\n公开接口不提供交易双方账号`;
    for (const [value, className] of [[time.toLocaleTimeString(undefined, { hour12: false, fractionalSecondDigits: 3 }), ''], [trade.buyerMaker ? '主动卖' : '主动买', trade.buyerMaker ? 'sell' : 'buy'], [bookPrice(trade.price), ''], [bookAmount(trade.quantity), ''], [bookAmount(Number(trade.price) * Number(trade.quantity)), '']]) {
      const cell = document.createElement('span'); cell.textContent = value; cell.className = className; row.append(cell);
    }
    return row;
  });
  $('recent-trades').replaceChildren(...rows);
  if (!rows.length) $('recent-trades').textContent = '等待成交';
  else state.tapeRenderTimer = setTimeout(renderTradeTape, 1000);
}

function onRecentTrade(event) {
  if (!(Number(event.T) > 0 && Number(event.p) > 0 && Number(event.q) > 0) || typeof event.m !== 'boolean' || !Number.isFinite(Number(event.p) * Number(event.q))) return;
  state.recentTrades.push({ id: event.a, time: Number(event.T), price: event.p, quantity: event.q, buyerMaker: event.m === true });
  if (!state.tapeRenderTimer) state.tapeRenderTimer = setTimeout(renderTradeTape, 250);
}

function onCurrentKline(event) {
  if (!state.chartLiveMode || !state.chart || event.s !== state.chartSymbol || event.k?.i !== state.chartInterval) return;
  const bar = MarketAnalytics.candle(event.k);
  if (!bar || bar.time < state.candles.at(-1).time || bar.time < (state.liveBar?.time || 0)) return;
  state.liveBar = bar;
  state.liveBarOpen = bar.isOpen;
  state.series.update(state.chartStyle === 'line' ? { time: bar.time, value: bar.close } : { time: bar.time, open: bar.open, high: bar.high, low: bar.low, close: bar.close });
  state.volumeSeries.update({ time: bar.time, value: Number(bar.volume), color: bar.close >= bar.open ? '#a7dccc' : '#f3b3b3' });
  $('chart-live-status').textContent = `${state.liveBarOpen ? '● 实时更新 · 当前 K 线未收盘' : '● K 线已收盘'} · ${new Date(Number(event.E)).toLocaleTimeString()} 本机`;
}

function connectOrderBook(symbol, generation) {
  if (generation !== state.orderBookGeneration || !orderBookActive()) return;
  let socket;
  const interval = state.orderBookInterval;
  const stream = `${symbol.toLowerCase()}@depth20/${symbol.toLowerCase()}@aggTrade/${symbol.toLowerCase()}@kline_${interval}`;
  try { socket = new WebSocket(`wss://data-stream.binance.vision/stream?streams=${stream}`); }
  catch { clearOrderBook('无法建立盘口连接'); return; }
  state.orderBookSocket = socket;
  clearOrderBook('正在连接实时盘口…');
  socket.onopen = () => { if (generation === state.orderBookGeneration) $('order-book-status').textContent = '已连接 · 等待盘口'; };
  socket.onmessage = (event) => {
    if (generation !== state.orderBookGeneration || !orderBookActive()) return;
    try {
      const packet = JSON.parse(event.data);
      const data = packet.data;
      if (!data) return;
      if (Array.isArray(data.bids) && Array.isArray(data.asks) && Number.isSafeInteger(data.lastUpdateId)) {
        state.orderBookAttempts = 0;
        renderOrderBook(data);
        clearTimeout(state.orderBookStaleTimer);
        state.orderBookStaleTimer = setTimeout(() => clearOrderBook('超过 10 秒无更新 · 等待盘口'), 10000);
      } else if (data.e === 'aggTrade') onRecentTrade(data);
      else if (data.e === 'kline') onCurrentKline(data);
    } catch { $('order-book-status').textContent = '盘口消息无效'; }
  };
  socket.onerror = () => { if (generation === state.orderBookGeneration) { $('order-book-status').textContent = '连接出错 · 等待重连'; socket.close(); } };
  socket.onclose = () => {
    if (generation !== state.orderBookGeneration) return;
    state.orderBookSocket = null;
    clearTimeout(state.orderBookStaleTimer);
    if (!orderBookActive()) { stopOrderBook('已暂停 · 返回市场页后恢复'); return; }
    clearOrderBook('连接中断 · 正在重连');
    const delay = Math.min(15000, 1000 * 2 ** Math.min(4, state.orderBookAttempts++));
    state.orderBookReconnect = setTimeout(() => connectOrderBook(symbol, generation), delay);
  };
}

function startOrderBook(symbol) {
  if (!orderBookActive()) return;
  if (!window.WebSocket) { clearOrderBook('浏览器不支持实时连接'); return; }
  const interval = $('interval').value;
  if (state.orderBookSymbol === symbol && state.orderBookInterval === interval && (state.orderBookSocket || state.orderBookReconnect)) return;
  stopOrderBook('正在切换交易对…');
  state.orderBookSymbol = symbol;
  state.orderBookInterval = interval;
  connectOrderBook(symbol, state.orderBookGeneration);
}

async function loadMarket() {
  const requestId = ++state.marketRequestId;
  try {
    if (!$('start').value || !$('end').value || $('start').value >= $('end').value) throw new Error('请选择有效的开始和结束日期。');
    const requestedSymbol = $('symbol').value.trim().toUpperCase();
    if (/^[A-Z0-9]{4,24}$/.test(requestedSymbol)) { state.marketSymbol = requestedSymbol; startOrderBook(requestedSymbol); }
    $('load-market').disabled = true;
    $('market-workspace').setAttribute('aria-busy', 'true');
    $('market-load-state').textContent = '正在加载…';
    const data = await api(`/api/candles?${query()}`);
    if (requestId !== state.marketRequestId) return;
    state.candles = data.candles;
    state.chartSymbol = data.symbol;
    state.chartInterval = data.interval;
    state.chartLiveMode = $('end').value > utcDate(new Date());
    state.liveBar = data.last_candle_open ? data.candles.at(-1) : null;
    state.liveBarOpen = data.last_candle_open;
    state.insightRangeKey = null;
    clearTimeout(state.insightTimer);
    state.marketSymbol = data.symbol;
    state.insights = data.insights || [];
    state.rangeDays = [...new Set(data.candles.map((bar) => utcDate(bar.time * 1000)))];
    updateSelectedPair(data.symbol);
    $('stat-symbol').textContent = data.symbol;
    $('stat-count').textContent = `${data.candles.length} 根`;
    $('stat-source').textContent = data.source;
    $('stat-time').textContent = `获取于 ${new Date(data.fetched_at).toLocaleString()}`;
    $('chart-live-status').textContent = data.last_candle_open ? '● 当前 K 线未收盘 · 等待实时更新' : '历史 K 线 · 已收盘';
    renderChart(data.candles);
    setupRangeNavigator();
    renderMarketList();
    startOrderBook(data.symbol);
    $('market-load-state').textContent = '已更新';
    toast(data.source.startsWith('cache:') ? '当前使用离线缓存；请核对获取时间和数据覆盖。' : '行情已加载；请检查数据覆盖后再回测。');
  } catch (error) {
    if (requestId === state.marketRequestId) { $('market-load-state').textContent = '加载失败'; toast(error.message.includes('历史数据未覆盖') ? '该币在所选日期内历史不足；请选择近 30 天、近 7 天或自定义更短区间。' : error.message); }
  }
  finally { if (requestId === state.marketRequestId) { $('load-market').disabled = false; $('market-workspace').removeAttribute('aria-busy'); } }
}

function setupRangeNavigator() {
  const days = state.rangeDays;
  if (!days.length) return;
  $('range-start').max = String(days.length - 1);
  $('range-end').max = String(days.length);
  $('range-start').value = '0';
  $('range-end').value = String(days.length);
  const daily = days.map((day) => state.candles.filter((bar) => utcDate(bar.time * 1000) === day).at(-1).close);
  const low = Math.min(...daily), high = Math.max(...daily);
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', daily.map((value, index) => `${index ? 'L' : 'M'} ${(index / Math.max(1, daily.length - 1) * 600).toFixed(1)} ${(48 - ((value - low) / (high - low || 1) * 42)).toFixed(1)}`).join(' '));
  path.setAttribute('fill', 'none'); path.setAttribute('stroke', '#8bb6f0'); path.setAttribute('stroke-width', '2');
  $('range-overview').replaceChildren(path);
  syncRangeLabels();
}

function syncRangeLabels() {
  const days = state.rangeDays;
  if (!days.length) return;
  const startIndex = Math.max(0, Math.min(days.length - 1, Number($('range-start').value)));
  const endIndex = Math.max(startIndex + 1, Math.min(days.length, Number($('range-end').value)));
  const start = days[startIndex];
  const end = endIndex === days.length ? addUtcDays(days.at(-1), 1) : days[endIndex];
  $('start').value = start; $('end').value = end;
  $('range-readout').textContent = `${start} → ${addUtcDays(end, -1)}（UTC）`;
  $('range-selection').style.left = `${startIndex / days.length * 100}%`;
  $('range-selection').style.width = `${(endIndex - startIndex) / days.length * 100}%`;
  const key = `${start}|${end}`;
  if (key !== state.insightRangeKey) {
    state.insightRangeKey = key;
    clearTimeout(state.insightTimer);
    state.insightTimer = setTimeout(() => renderInsights(start, end), 80);
  }
}

function applyRangeFromSlider(changed) {
  if (!state.rangeDays.length) return;
  const start = $('range-start'), end = $('range-end');
  if (Number(start.value) >= Number(end.value)) {
    if (changed === 'start') start.value = String(Number(end.value) - 1);
    else end.value = String(Number(start.value) + 1);
  }
  syncRangeLabels();
  if (state.chart) {
    state.syncingRange = true;
    try { const from = dayTimestamp($('start').value); state.chart.timeScale().setVisibleRange({ from, to: Math.max(from + intervalSeconds[$('interval').value], dayTimestamp($('end').value) - intervalSeconds[$('interval').value]) }); }
    finally { state.syncingRange = false; }
  }
}

const insightMetrics = [
  ['insight-momentum', 'momentum_20', (value) => `${value > 0 ? '+' : ''}${value.toFixed(2)}%`],
  ['insight-volume', 'volume_ratio_20', (value) => `${value.toFixed(2)}×`],
  ['insight-drawdown', 'drawdown_20', (value) => `${value.toFixed(2)}%`]
];

function updateInsightHover(index) {
  const point = state.insightVisible[index];
  if (!point) return;
  insightMetrics.forEach(([id, key, format]) => {
    const card = $(id), value = point[key];
    card.querySelector('strong').textContent = value === null || value === undefined ? '样本不足' : format(value);
    const cursor = card.querySelector('.insight-cursor');
    if (cursor) { const x = 12 + index / Math.max(1, state.insightVisible.length - 1) * 276; cursor.setAttribute('x1', x); cursor.setAttribute('x2', x); cursor.style.display = ''; }
  });
}

function renderInsights(start, end) {
  state.insightVisible = state.insights.filter((item) => item.time >= dayTimestamp(start) && item.time < dayTimestamp(end));
  insightMetrics.forEach(([id, key]) => {
    const card = $(id), svg = card.querySelector('svg');
    const values = state.insightVisible.map((item) => item[key]).filter((value) => value !== null && value !== undefined);
    svg.replaceChildren();
    if (!values.length) { card.querySelector('strong').textContent = '样本不足'; return; }
    const low = Math.min(...values), high = Math.max(...values);
    let drawing = false;
    const points = state.insightVisible.map((item, index) => {
      const value = item[key];
      if (value === null || value === undefined) { drawing = false; return ''; }
      const x = 12 + index / Math.max(1, state.insightVisible.length - 1) * 276;
      const y = 86 - (value - low) / (high - low || 1) * 72;
      const command = drawing ? 'L' : 'M'; drawing = true;
      return `${command} ${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(' ');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', points); path.setAttribute('class', 'insight-line');
    const cursor = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    cursor.setAttribute('y1', '8'); cursor.setAttribute('y2', '92'); cursor.setAttribute('class', 'insight-cursor'); cursor.style.display = 'none';
    svg.append(path, cursor);
    svg.onpointermove = (event) => { const rect = svg.getBoundingClientRect(); updateInsightHover(Math.max(0, Math.min(state.insightVisible.length - 1, Math.round((event.clientX - rect.left) / rect.width * (state.insightVisible.length - 1))))); };
    svg.onpointerleave = () => updateInsightHover(state.insightVisible.length - 1);
  });
  updateInsightHover(state.insightVisible.length - 1);
}

const offlineCandidates = ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'DOGE', 'ADA', 'AVAX', 'LINK', 'SUI', 'PEPE'].map((base) => ({ symbol: `${base}USDT`, base, quote: 'USDT', status: 'UNVERIFIED', quote_volume: null, change_percent: null }));
function formatVolume(value) {
  if (value === null || value === undefined) return '成交额未知';
  const number = Number(value);
  return `24h ${number >= 1e9 ? (number / 1e9).toFixed(1) + 'B' : number >= 1e6 ? (number / 1e6).toFixed(1) + 'M' : number >= 1e3 ? (number / 1e3).toFixed(1) + 'K' : number.toFixed(0)}`;
}

function renderMarketList() {
  const queryText = $('market-search').value.trim().toUpperCase();
  const quote = $('quote-filter').value;
  let items = state.symbols.filter((item) => (!quote || item.quote === quote) && (!queryText || item.symbol.includes(queryText) || item.base.includes(queryText)));
  if (state.marketTab === 'favorites') {
    const bySymbol = new Map(items.map((item) => [item.symbol, item]));
    items = state.favorites.map((symbol) => {
      const suffix = ['USDT', 'BTC', 'ETH', 'BNB'].find((value) => symbol.endsWith(value)) || '';
      return bySymbol.get(symbol) || { symbol, base: suffix ? symbol.slice(0, -suffix.length) : symbol, quote: suffix, status: 'UNVERIFIED', quote_volume: null, change_percent: null };
    }).filter((item) => (!quote || item.quote === quote) && (!queryText || item.symbol.includes(queryText)));
  }
  $('market-list').replaceChildren(...items.slice(0, 100).map((item) => {
    const row = document.createElement('div'); row.className = 'market-row'; row.setAttribute('role', 'listitem');
    const favorite = document.createElement('button'); favorite.type = 'button'; favorite.className = 'market-favorite'; favorite.textContent = state.favorites.includes(item.symbol) ? '★' : '☆'; favorite.setAttribute('aria-label', `${state.favorites.includes(item.symbol) ? '取消自选' : '加入自选'} ${item.symbol}`);
    favorite.addEventListener('click', () => { state.favorites = state.favorites.includes(item.symbol) ? state.favorites.filter((name) => name !== item.symbol) : [...state.favorites, item.symbol]; localStorage.setItem('crypto-market-favorites', JSON.stringify(state.favorites)); renderMarketList(); });
    const select = document.createElement('button'); select.type = 'button'; select.className = `market-pair${$('symbol').value === item.symbol ? ' active' : ''}`; select.setAttribute('aria-label', `查看 ${item.symbol} 行情`);
    const name = document.createElement('span'); name.className = 'market-name'; const title = document.createElement('strong'); title.textContent = item.base; const detail = document.createElement('small'); detail.textContent = item.quote; name.append(title, detail);
    const move = document.createElement('span'); move.className = 'market-move'; const change = Number(item.change_percent); move.textContent = item.change_percent === null ? '—' : `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`; move.classList.add(item.change_percent === null ? 'unverified' : change >= 0 ? 'positive' : 'negative'); const volume = document.createElement('small'); volume.textContent = item.status === 'UNVERIFIED' ? '未核验' : formatVolume(item.quote_volume); move.append(volume);
    select.append(name, move); select.addEventListener('click', () => { $('symbol').value = item.symbol; updateSelectedPair(item.symbol); renderMarketList(); loadMarket(); }); row.append(favorite, select); return row;
  }));
  if (!items.length) $('market-list-status').textContent = state.marketTab === 'favorites' ? '自选为空，可点币种旁的星标添加。' : '没有匹配的交易对，可在自定义日期里手动输入。';
}

async function loadSymbols() {
  const requestId = ++state.symbolRequestId;
  const queryText = $('market-search').value.trim();
  $('market-list-status').textContent = '正在加载交易对…';
  try {
    const quote = $('quote-filter').value;
    const data = await api(`/api/symbols?q=${encodeURIComponent(queryText)}&quote=${encodeURIComponent(quote)}`);
    if (requestId !== state.symbolRequestId) return;
    state.symbols = data.items;
    $('market-list-status').textContent = data.stale ? `使用上次成功目录 · ${data.items.length} 个结果` : `${queryText ? '优先显示匹配币种' : '按 24 小时成交额排序'} · ${data.items.length} 个结果`;
  } catch (error) {
    if (requestId !== state.symbolRequestId) return;
    state.symbols = offlineCandidates;
    $('market-list-status').textContent = '交易所目录暂不可用；下方是未核验的常见候选。';
  }
  renderMarketList();
}

function initializeMarketExplorer() {
  try { const saved = JSON.parse(localStorage.getItem('crypto-market-favorites') || '[]'); state.favorites = Array.isArray(saved) ? saved.filter((value) => typeof value === 'string') : []; }
  catch { state.favorites = []; }
  setPreset(90, false);
  loadSymbols();
  loadMarket();
}

const descriptions = {
  sma_cross: '短均线上穿长均线买入，下穿卖出；信号仅使用已收盘 K 线。',
  breakout: '收盘价突破此前窗口最高价买入，跌破最低价卖出。',
  dca: '按 UTC 固定间隔投入指定比例的可用现金。',
  buy_hold: '首根 K 线收盘后买入并持有，作为比较基准。'
};

function strategyParams() {
  const kind = $('strategy-kind').value;
  $('strategy-description').textContent = descriptions[kind];
  const fields = kind === 'sma_cross' ? [['short', '短均线周期', 7], ['long', '长均线周期', 30]] : kind === 'breakout' ? [['window', '突破窗口', 20]] : kind === 'dca' ? [['every_days', '间隔天数', 7], ['fraction', '资金比例', 0.1]] : [];
  $('strategy-params').replaceChildren(...fields.map(([key, label, value]) => {
    const wrapper = document.createElement('label'); wrapper.textContent = label;
    const input = document.createElement('input'); input.id = `param-${key}`; input.type = 'number'; input.min = '0.0001'; input.step = 'any'; input.value = value;
    wrapper.append(input); return wrapper;
  }));
}

function parameters() {
  const result = {};
  $('strategy-params').querySelectorAll('input').forEach((input) => {
    const key = input.id.replace('param-', '');
    result[key] = key === 'fraction' ? input.value : Number(input.value);
  });
  return result;
}

async function runBacktest() {
  try {
    const body = { ...Object.fromEntries(query()), kind: $('strategy-kind').value, parameters: parameters(), initial_cash: $('initial-cash').value, fee_rate: $('fee-rate').value, slippage_rate: $('slippage-rate').value, source_url: $('source-url').value || 'https://example.org/own-rule', note: $('research-note').value };
    const { id, result } = await api('/api/backtests', { method: 'POST', body: JSON.stringify(body) });
    const metrics = [['总收益', result.total_return], ['最大回撤', result.max_drawdown], ['交易次数', result.fills.length], ['手续费总额', result.fees_total], ['胜率', result.win_rate], ['买入持有基准', result.benchmark_return], ['年化收益', result.annualized_return ?? '不足 30 天']];
    $('backtest-summary').replaceChildren(...metrics.map(([name, value]) => { const item = document.createElement('div'); item.className = 'metric'; const label = document.createElement('span'); label.textContent = name; const number = document.createElement('strong'); number.textContent = String(value); item.append(label, number); return item; }));
    $('fills-body').replaceChildren(...result.fills.map((fill) => { const row = document.createElement('tr'); [fill.signal_at, fill.filled_at, fill.side === 'BUY' ? '模拟买入' : '模拟卖出', fill.quantity, fill.price, fill.fee, fill.cash_after, fill.coins_after].forEach((value) => { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); }); return row; }));
    if (state.candles.length) renderChart(state.candles, result.fills, true);
    toast(`回测 #${id} 已保存。历史模拟不代表未来收益。`);
  } catch (error) { toast(error.message); }
}

async function saveResearch() {
  try {
    const url = $('source-url').value;
    if (!url) throw new Error('请先填写策略来源链接。');
    await api('/api/research', { method: 'POST', body: JSON.stringify({ kind: $('strategy-kind').value, parameters: parameters(), version: '1', source_url: url, note: $('research-note').value }) });
    toast('策略来源与笔记已保存。');
  } catch (error) { toast(error.message); }
}

function chooseStrategySource(item) {
  state.selectedStrategySource = item;
  $('selected-source-name').textContent = item.name;
  $('selected-source-url').href = item.url;
  $('selected-source-url').hidden = false;
  $('selected-source-revision').textContent = `版本 ${item.revision.slice(0, 12)} · ${item.license}`;
  renderStrategySources();
}

function renderStrategySources() {
  const term = $('strategy-source-search').value.trim().toLowerCase();
  const items = state.strategySources.filter((item) => item.name.toLowerCase().includes(term));
  $('strategy-source-list').replaceChildren(...items.map((item) => {
    const button = document.createElement('button');
    button.type = 'button'; button.className = `source-item${state.selectedStrategySource?.path === item.path ? ' active' : ''}`;
    const name = document.createElement('strong'); name.textContent = item.name;
    const detail = document.createElement('span'); detail.textContent = `${item.engine} · ${item.license}`;
    button.append(name, detail); button.addEventListener('click', () => chooseStrategySource(item)); return button;
  }));
  if (!items.length) $('strategy-source-list').textContent = '没有匹配的策略文件。';
}

async function loadStrategySources() {
  $('strategy-source-status').textContent = '正在加载目录…';
  try {
    const data = await api('/api/strategy-sources');
    state.strategySources = data.items;
    state.strategySourcesLoaded = true;
    $('strategy-source-status').textContent = data.stale ? `离线目录 · ${data.items.length} 个文件` : `${data.items.length} 个策略文件`;
    $('daily-strategy').textContent = data.daily.name;
    $('daily-strategy').onclick = () => chooseStrategySource(data.daily);
    renderStrategySources();
    loadSavedSourceNotes();
  } catch (error) { $('strategy-source-status').textContent = '目录不可用'; $('strategy-source-list').textContent = error.message; }
}

async function loadSavedSourceNotes() {
  try {
    const data = await api('/api/strategy-notes');
    $('saved-source-notes').replaceChildren(...data.items.slice(0, 5).map((item) => {
      const row = document.createElement('p');
      const name = document.createElement('strong'); name.textContent = `${item.path.split('/').at(-1)} · ${item.revision.slice(0, 10)}`;
      const note = document.createElement('span'); note.textContent = ` ${item.note}`;
      row.append(name, note); return row;
    }));
    if (!data.items.length) $('saved-source-notes').textContent = '还没有保存的开源策略学习笔记。';
  } catch (error) { $('saved-source-notes').textContent = error.message; }
}

async function saveExternalStrategyNote() {
  if (!state.selectedStrategySource) { toast('请先从目录选择策略文件。'); return; }
  try {
    const item = state.selectedStrategySource;
    await api('/api/strategy-notes', { method: 'POST', body: JSON.stringify({ path: item.path, revision: item.revision, note: $('external-strategy-note').value }) });
    $('external-strategy-note').value = '';
    toast('来源版本与学习笔记已保存。');
    loadSavedSourceNotes();
  } catch (error) { toast(error.message); }
}

async function loadRecords() {
  try {
    const data = await api('/api/backtests');
    $('records-list').replaceChildren(...data.items.map((item) => { const button = document.createElement('button'); button.textContent = `#${item.id} · ${item.symbol} · ${item.strategy_kind} · 收益 ${item.total_return}`; button.addEventListener('click', async () => { const detail = await api(`/api/backtests/${item.id}`); toast(`${detail.symbol}：${detail.fills.length} 笔模拟成交，数据版本 ${detail.data_checksum.slice(0, 10)}`); }); return button; }));
    if (!data.items.length) $('records-list').textContent = '暂无回测记录。';
  } catch (error) { toast(error.message); }
}

document.querySelectorAll('.navlink').forEach((button) => button.addEventListener('click', () => showPage(button.dataset.page)));
$('load-market').addEventListener('click', loadMarket);
$('run-backtest').addEventListener('click', runBacktest);
$('save-research').addEventListener('click', saveResearch);
$('strategy-source-search').addEventListener('input', renderStrategySources);
$('save-external-note').addEventListener('click', saveExternalStrategyNote);
$('wallet-address').addEventListener('input', () => { ++assetRequest; clearAssets(); $('asset-status').textContent = '地址已变化，请刷新'; });
$('connect-wallet').addEventListener('click', connectWallet);
$('refresh-assets').addEventListener('click', loadAssets);
$('connect-read-key').addEventListener('click', connectReadKey);
$('enable-trading').addEventListener('click', configureTrade);
$('disable-trading').addEventListener('click', disableTrade);
$('trade-preview').addEventListener('click', previewTrade);
$('refresh-orders').addEventListener('click', loadTradeOrders);
$('trade-dialog-submit').addEventListener('click', submitTradeDialog);
$('trade-dialog-close').addEventListener('click', () => $('trade-dialog').close());
$('trade-type').addEventListener('change', () => { $('trade-limit-label').hidden = $('trade-type').value === 'MARKET'; });
$('strategy-kind').addEventListener('change', strategyParams);
$('symbol').addEventListener('change', () => { $('symbol').value = $('symbol').value.trim().toUpperCase(); updateSelectedPair($('symbol').value); renderMarketList(); });
let symbolSearchTimer;
$('market-search').addEventListener('input', () => { clearTimeout(symbolSearchTimer); symbolSearchTimer = setTimeout(loadSymbols, 260); });
$('quote-filter').addEventListener('change', loadSymbols);
document.querySelectorAll('[data-market-tab]').forEach((button) => button.addEventListener('click', () => { state.marketTab = button.dataset.marketTab; document.querySelectorAll('[data-market-tab]').forEach((item) => item.classList.toggle('active', item === button)); renderMarketList(); }));
document.querySelectorAll('[data-interval]').forEach((button) => button.addEventListener('click', () => { $('interval').value = button.dataset.interval; document.querySelectorAll('[data-interval]').forEach((item) => item.classList.toggle('active', item === button)); setPreset(({ '15m': 7, '1h': 30, '4h': 90, '1d': 90 })[button.dataset.interval]); }));
document.querySelectorAll('[data-chart-style]').forEach((button) => button.addEventListener('click', () => { state.chartStyle = button.dataset.chartStyle; document.querySelectorAll('[data-chart-style]').forEach((item) => item.classList.toggle('active', item === button)); if (state.candles.length) renderChart(state.candles, state.fills, true); }));
document.querySelectorAll('[data-days]').forEach((button) => button.addEventListener('click', () => setPreset(Number(button.dataset.days))));
$('range-start').addEventListener('input', () => applyRangeFromSlider('start'));
$('range-end').addEventListener('input', () => applyRangeFromSlider('end'));
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopOrderBook('已暂停 · 返回页面后恢复');
  else if (state.marketSymbol && orderBookActive()) startOrderBook(state.marketSymbol);
});
$('chart-fit').addEventListener('click', () => { if (state.chart) { state.chart.timeScale().fitContent(); $('range-start').value = '0'; $('range-end').value = String(state.rangeDays.length); syncRangeLabels(); } });
for (const [id, factor] of [['chart-zoom-in', 0.75], ['chart-zoom-out', 1.35]]) $(id).addEventListener('click', () => { const scale = state.chart?.timeScale(); const range = scale?.getVisibleLogicalRange(); if (!range) return; const center = (range.from + range.to) / 2; const half = (range.to - range.from) * factor / 2; scale.setVisibleLogicalRange({ from: center - half, to: center + half }); });
initializeMarketExplorer();
strategyParams();
