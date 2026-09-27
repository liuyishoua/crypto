const $ = (id) => document.getElementById(id);
const state = { chart: null, series: null, markers: null, candles: [] };

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
  document.querySelectorAll('.page').forEach((page) => page.classList.toggle('active', page.id === `page-${name}`));
  document.querySelectorAll('.navlink').forEach((button) => button.classList.toggle('active', button.dataset.page === name));
  if (name === 'records') loadRecords();
  if (name === 'assets') loadAssets();
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
    $('asset-status').textContent = '已更新';
    $('asset-updated').textContent = new Date().toLocaleString();
    renderAssetRows('binance-assets', data.groups['binance-spot'], false);
    renderAssetRows('onchain-assets', data.groups.onchain, true);
    const notices = Object.values(data.errors);
    Object.entries(data.discovery).forEach(([chain, status]) => { if (!status.complete) notices.push(`${chain === '1' ? 'Ethereum' : 'BNB Smart Chain'} 资产发现不完整：${status.error || '索引器暂不可用'}；已知余额仍显示。最近查询 ${status.observed_at ? new Date(status.observed_at).toLocaleString() : '未知'}`); });
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

function renderChart(candles, fills = []) {
  const container = $('chart');
  if (!window.LightweightCharts) { container.textContent = '图表组件暂不可用，请查看下方数据。'; return; }
  if (state.chart) state.chart.remove();
  const chart = LightweightCharts.createChart(container, { width: container.clientWidth, height: container.clientHeight, layout: { background: { color: '#ffffff' }, textColor: '#667085' }, grid: { vertLines: { color: '#f3f5f8' }, horzLines: { color: '#f3f5f8' } }, rightPriceScale: { borderColor: '#e8ebf0' }, timeScale: { borderColor: '#e8ebf0' } });
  const series = chart.addSeries(LightweightCharts.CandlestickSeries, { upColor: '#249e81', downColor: '#df6a6a', borderVisible: false, wickUpColor: '#249e81', wickDownColor: '#df6a6a' });
  series.setData(candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
  const markers = fills.map((fill) => ({ time: Math.floor(Date.parse(fill.filled_at) / 1000), position: fill.side === 'BUY' ? 'belowBar' : 'aboveBar', color: fill.side === 'BUY' ? '#249e81' : '#df6a6a', shape: fill.side === 'BUY' ? 'arrowUp' : 'arrowDown', text: `${fill.side === 'BUY' ? '模拟买入' : '模拟卖出'} ${Number(fill.price).toFixed(3)}` }));
  if (markers.length) LightweightCharts.createSeriesMarkers(series, markers);
  chart.timeScale().fitContent();
  state.chart = chart;
  state.series = series;
}

async function loadMarket() {
  try {
    const data = await api(`/api/candles?${query()}`);
    state.candles = data.candles;
    $('stat-symbol').textContent = data.symbol;
    $('stat-count').textContent = `${data.candles.length} 根`;
    $('stat-source').textContent = data.source;
    $('stat-time').textContent = `获取于 ${new Date(data.fetched_at).toLocaleString()}`;
    renderChart(data.candles);
    toast('行情已加载；请检查数据覆盖后再回测。');
  } catch (error) { toast(error.message); }
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
    if (state.candles.length) renderChart(state.candles, result.fills);
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
$('wallet-address').addEventListener('input', () => { ++assetRequest; clearAssets(); $('asset-status').textContent = '地址已变化，请刷新'; });
$('connect-wallet').addEventListener('click', connectWallet);
$('refresh-assets').addEventListener('click', loadAssets);
$('connect-read-key').addEventListener('click', connectReadKey);
$('strategy-kind').addEventListener('change', strategyParams);
$('symbol').addEventListener('input', async () => {
  const query = $('symbol').value.trim();
  if (query.length < 2) return;
  try { const data = await api(`/api/symbols?q=${encodeURIComponent(query)}`); $('symbol-hint').textContent = data.items.slice(0, 5).map((item) => item.symbol).join(' · ') || '没有匹配的现货交易对'; } catch (error) { $('symbol-hint').textContent = error.message; }
});
strategyParams();
