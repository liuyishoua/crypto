from decimal import Decimal

from .market import Candle


def calculate_insights(candles: tuple[Candle, ...]) -> list[dict]:
    """Describe price and volume patterns without implying knowledge of trader identity."""
    result = []
    for index, bar in enumerate(candles):
        prior = candles[index - 20:index] if index >= 20 else ()
        peak = max(item.close for item in candles[max(0, index - 19):index + 1])
        average_volume = sum((item.volume for item in prior), Decimal(0)) / 20 if prior else Decimal(0)
        result.append({
            "time": int(bar.open_at.timestamp()),
            "momentum_20": round(float((bar.close / candles[index - 20].close - 1) * 100), 4) if prior else None,
            "volume_ratio_20": round(float(bar.volume / average_volume), 4) if average_volume > 0 else None,
            "drawdown_20": round(float((bar.close / peak - 1) * 100), 4),
        })
    return result
