from datetime import datetime, timedelta, timezone
from decimal import Decimal

from crypto_app.insights import calculate_insights
from crypto_app.market import Candle


def candles(closes, volumes):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return tuple(Candle(start + timedelta(days=index), close, close, close, close, volume) for index, (close, volume) in enumerate(zip(closes, volumes)))


def test_insights_use_only_prior_volume_and_report_warmup():
    bars = candles([Decimal(100)] * 20 + [Decimal(120), Decimal(108)], [Decimal(100)] * 20 + [Decimal(200), Decimal(50)])
    result = calculate_insights(bars)
    assert len(result) == 22
    assert result[19]["momentum_20"] is None
    assert result[19]["volume_ratio_20"] is None
    assert result[20]["momentum_20"] == 20.0
    assert result[20]["volume_ratio_20"] == 2.0
    assert result[20]["drawdown_20"] == 0.0
    assert result[21]["drawdown_20"] == -10.0
    assert result[21]["volume_ratio_20"] == round(50 / 105, 4)


def test_zero_prior_volume_is_unknown_not_infinite():
    bars = candles([Decimal(10)] * 21, [Decimal(0)] * 20 + [Decimal(100)])
    assert calculate_insights(bars)[20]["volume_ratio_20"] is None
