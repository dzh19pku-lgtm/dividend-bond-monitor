"""时序观察指标，不输出买卖指令；缺日不压缩成完整交易日窗口。"""
from datetime import datetime, timedelta
from statistics import mean, stdev
from .calendar import CalendarUnknown
from .config import BOND_SERIES, index_series

def features(rows, calendar):
    result = []
    values = []
    seen_available = None
    for i, row in enumerate(rows):
        current = dict(row)
        value = row["spread_pp"]
        if value is not None:
            values.append(value)
            seen_available = max(filter(None, [seen_available, row["available_at"]]), key=datetime.fromisoformat)
        current.update(mean_252=None, std_252=None, mean_756=None, std_756=None, zscore_252=None,
                       percentile_expanding=None, range_position=None, sample_count=len(values))
        if value is not None and len(values) >= 252:
            # 分位使用截至本行的样本（并列取中位秩），不回看后续数据。
            current["percentile_expanding"] = 100 * (sum(v < value for v in values) + 0.5 * sum(v == value for v in values)) / len(values)
            low, high = min(values), max(values)
            current["range_position"] = None if high == low else 100 * (value - low) / (high - low)
        for window in (252, 756):
            chunk = rows[max(0, i - window + 1):i + 1]
            if len(chunk) == window and all(r["spread_pp"] is not None for r in chunk):
                data = [r["spread_pp"] for r in chunk]
                current[f"mean_{window}"] = mean(data)
                current[f"std_{window}"] = stdev(data)  # 样本标准差 ddof=1，包含当前日。
                if window == 252 and current["std_252"] > 0:
                    current["zscore_252"] = (value - current["mean_252"]) / current["std_252"]
        # 整个扩展统计样本中最晚获得的输入约束其真实可用时间。
        current["features_available_at"] = seen_available if value is not None else None
        current["earliest_trade_open"] = None
        current["tplus1_ready"] = False
        if value is not None:
            try:
                target = calendar.next_open(row["trade_date"])
                current["tplus1_open"] = target.isoformat()
                current["earliest_trade_open"] = calendar.usable_open(row["trade_date"], seen_available)
                current["tplus1_ready"] = datetime.fromisoformat(seen_available) <= target - timedelta(minutes=30)
            except CalendarUnknown:
                current["tplus1_open"] = None
        result.append(current)
    return result

def aligned_rows(latest, code, calendar, expected):
    equity = {d: r for (s, d), r in latest.items() if s == index_series(code) and d <= expected}
    bonds = {d: r for (s, d), r in latest.items() if s == BOND_SERIES and d <= expected}
    if not equity:
        return []
    start = min(equity)
    dates = calendar.sessions(start, expected)
    rows = []
    for day in dates:
        a, b = equity.get(day), bonds.get(day)
        matched = a is not None and b is not None
        available = max((a["available_at"], b["available_at"]), key=datetime.fromisoformat) if matched else None
        rows.append(dict(trade_date=day, index_code=code, dividend_percent=a["value"] if a else None,
                         bond_percent=b["value"] if b else None, spread_pp=round(a["value"] - b["value"], 8) if matched else None,
                         dp1_percent=a.get("dp1_percent") if a else None, available_at=available,
                         dividend_observed_at=a["observed_at"] if a else None, bond_observed_at=b["observed_at"] if b else None,
                         dividend_source=a["source_id"] if a else None, bond_source=b["source_id"] if b else None,
                         dividend_definition=a["definition_id"] if a else None, bond_definition=b["definition_id"] if b else None,
                         source_published_at=None, status="matched" if matched else "missing_component",
                         dividend_revision=a["revision"] if a else None, bond_revision=b["revision"] if b else None))
    return features(rows, calendar)
