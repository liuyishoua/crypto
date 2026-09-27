// Timestamps stay in UTC in market data; only their labels change for readers in China.
globalThis.MarketPresentation = Object.freeze({
  clock(timestamp, beijing = true, date = true, milliseconds = false) {
    const value = new Date(Number(timestamp) + (beijing ? 8 * 60 * 60 * 1000 : 0)).toISOString();
    return `${date ? `${value.slice(0, 10)} ` : ''}${value.slice(11, milliseconds ? 23 : 19)}`;
  },
  dualTime(timestamp, milliseconds = false) {
    return `${this.clock(timestamp, true, true, milliseconds)} 北京时间 (UTC+8) · ${this.clock(timestamp, false, true, milliseconds)} UTC`;
  },
  chartTime(seconds, interval) {
    const value = this.clock(Number(seconds) * 1000);
    return interval === '1d' ? value.slice(5, 10) : value.slice(11, 16);
  },
  priceMove(trades) {
    if (trades.length < 2) return null;
    const first = Number(trades[0].price), last = Number(trades[trades.length - 1].price);
    return first > 0 && Number.isFinite(last) ? (last / first - 1) * 100 : null;
  },
  bookReading(depthShare, flowShare, tradeCount, observedSeconds) {
    if (depthShare === null || !Number.isFinite(depthShare)) {
      return { headline: '等待盘口快照', detail: '取得买卖挂单后，再比较已成交的主动方向。' };
    }
    if (flowShare === null || !Number.isFinite(flowShare) || tradeCount < 10 || observedSeconds < 15) {
      return { headline: '成交样本不足，先观察挂单', detail: '至少观察 15 秒且取得 10 条聚合成交，才比较挂单和成交。' };
    }
    const side = (share) => share > 55 ? '偏买' : share < 45 ? '偏卖' : '接近平衡';
    const depth = side(depthShare), flow = side(flowShare);
    const discord = depth !== flow;
    return {
      headline: `挂单${depth} · 成交${flow}`,
      detail: discord
        ? '两项读数不同向：挂单是尚未成交的意向，可以撤销；成交才是已发生的交易。不能据此断言价格将涨跌。'
        : '两项读数暂时同向：挂单可以随时撤销，成交也不能单独证明价格之后的方向。'
    };
  }
});
