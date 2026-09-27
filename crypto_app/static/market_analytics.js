globalThis.MarketAnalytics = Object.freeze({
  depth(bids, asks, levels) {
    const sum = (rows) => rows.slice(0, levels).reduce((total, [price, quantity]) => total + Number(price) * Number(quantity), 0);
    const bidNotional = sum(bids);
    const askNotional = sum(asks);
    return { bidNotional, askNotional, buyShare: bidNotional + askNotional ? bidNotional / (bidNotional + askNotional) * 100 : null };
  },
  flow(trades, since) {
    let buyNotional = 0;
    let sellNotional = 0;
    let count = 0;
    for (const trade of trades) {
      if (trade.time < since) continue;
      const notional = Number(trade.price) * Number(trade.quantity);
      if (!Number.isFinite(notional) || notional < 0) continue;
      if (trade.buyerMaker) sellNotional += notional;
      else buyNotional += notional;
      count++;
    }
    return { buyNotional, sellNotional, buyShare: buyNotional + sellNotional ? buyNotional / (buyNotional + sellNotional) * 100 : null, count };
  },
  candle(kline) {
    if (!kline || typeof kline.x !== 'boolean') return null;
    const time = Number(kline.t) / 1000;
    const open = Number(kline.o), high = Number(kline.h), low = Number(kline.l), close = Number(kline.c), volume = Number(kline.v);
    if (![time, open, high, low, close, volume].every(Number.isFinite) || time <= 0 || low <= 0 || volume < 0 || low > Math.min(open, close) || high < Math.max(open, close)) return null;
    return { time, open, high, low, close, volume: String(kline.v), isOpen: !kline.x };
  }
});
