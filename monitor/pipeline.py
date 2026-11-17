from datetime import datetime, timedelta, date, timezone
import csv
from io import StringIO
import json
import logging
from pathlib import Path
from .calendar import TradingCalendar, CalendarUnknown, SH
from .config import ROOT, INDEXES, BOND_SERIES, DEFINITION, index_series
from .sources import fetch_csi, fetch_bond, SourceError, utc_now
from .store import Store, write_json, atomic_text
from .analytics import aligned_rows
from .calendar_refresh import refresh_calendar

LOG = logging.getLogger(__name__)

def update(data_root=ROOT / "data", now=None, bootstrap=False, equity_fetch=fetch_csi, bond_fetch=fetch_bond):
    now = now or datetime.now(timezone.utc)
    calendar = TradingCalendar(Path(data_root) / "calendar.json")
    store = Store(data_root)
    status = {"started_at": now.isoformat(), "finished_at": None, "expected_date": None,
              "state": "error", "sources": {}, "errors": []}
    with store.lock():
        try:
            local_now = now.astimezone(SH)
            if str(local_now.year) not in calendar.years or (local_now.month >= 11 and str(local_now.year + 1) not in calendar.years):
                status["calendar_refresh"] = refresh_calendar(data_root, local_now)
                if status["calendar_refresh"].get("requires_review"):
                    raise CalendarUnknown("上交所日历与本地冲突，暂停采集并保留历史，请核验休市安排")
                calendar = TradingCalendar(Path(data_root) / "calendar.json")
            expected = calendar.expected_date(now)
            status["expected_date"] = expected
            if not bootstrap and (not calendar.is_session(now.astimezone(SH).date()) or now.astimezone(SH).hour < 15):
                status["state"] = "skipped_non_session_or_before_close"
            else:
                start = (date.fromisoformat(expected) - timedelta(days=40)).isoformat()
                jobs = [(index_series(code), lambda c=code: equity_fetch(c)) for code in INDEXES]
                jobs.append((BOND_SERIES, lambda: bond_fetch(start, expected)))
                for series, fetcher in jobs:
                    try:
                        observations = fetcher()
                        if not observations:
                            raise SourceError("空响应")
                        if any(r["trade_date"] > expected for r in observations):
                            raise SourceError("源返回尚未收盘或未来日期")
                        if series != BOND_SERIES and any(not calendar.is_session(r["trade_date"]) for r in observations):
                            raise SourceError("指数响应包含非 A 股交易日")
                        outcome = store.merge(observations)
                        latest = max(r["trade_date"] for (s, _), r in store.latest(series).items()) if store.latest(series) else None
                        status["sources"][series] = {**outcome, "latest_date": latest, "state": "current" if latest == expected and not outcome["quarantined"] else "stale_or_quarantined"}
                        LOG.info("%s %s", series, status["sources"][series])
                    except Exception as exc:
                        # 每个源独立失败；不以空文件覆盖已成功的历史。
                        LOG.exception("源更新失败 %s", series)
                        status["sources"][series] = {"state": "error", "error": f"{type(exc).__name__}: {exc}"}
                status["state"] = "current" if all(s["state"] == "current" for s in status["sources"].values()) else "degraded"
        except Exception as exc:
            status["errors"].append(f"{type(exc).__name__}: {exc}")
            LOG.exception("更新失败")
        status["finished_at"] = utc_now()
        write_json(Path(data_root) / "status.json", status)
    return status

CSV_FIELDS = ["trade_date", "index_code", "dividend_percent", "bond_percent", "spread_pp", "dp1_percent", "status",
              "dividend_source", "bond_source", "dividend_definition", "bond_definition", "source_published_at",
              "dividend_observed_at", "bond_observed_at", "available_at", "features_available_at", "earliest_trade_open", "tplus1_open", "tplus1_ready",
              "dividend_revision", "bond_revision", "sample_count", "mean_252", "std_252", "mean_756", "std_756", "zscore_252", "percentile_expanding", "range_position"]

def csv_text(rows):
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return "\ufeff" + stream.getvalue()

def build(data_root=ROOT / "data", site_root=ROOT / "site", now=None, as_of=None):
    now = now or datetime.now(timezone.utc)
    if as_of:
        now = datetime.fromisoformat(as_of)
        if now.tzinfo is None:
            raise SourceError("as-of 必须包含时区")
    data_root, site_root = Path(data_root), Path(site_root)
    calendar = TradingCalendar(data_root / "calendar.json")
    warnings = []
    try:
        expected = calendar.expected_date(now)
    except CalendarUnknown as exc:
        expected = None
        warnings.append(str(exc))
    latest = Store(data_root).latest(as_of=as_of)
    status_path = data_root / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {"state": "not_run"}
    if as_of:
        status = {"state": "historical_as_of", "finished_at": None, "sources": {}}
    elif status.get("calendar_refresh", {}).get("state") == "error":
        warnings.append("交易日历刷新失败：" + status["calendar_refresh"]["error"])
    manifest = {"schema_version": 1, "generated_at": now.isoformat(), "as_of": as_of, "expected_date": expected,
                "definition": DEFINITION, "dividend_label": "官方股息率 D/P2（非已验证 TTM）", "bond_label": "中债国债到期收益率曲线 · 10年",
                "unit": "percent", "spread_unit": "percentage_point", "run": status, "warnings": warnings,
                "calendar": calendar.payload, "indexes": []}
    for code, name in INDEXES.items():
        # 日历失效时仍展示历史，但不得声称已更新到最新交易日。
        known_dates = [d for (s, d) in latest if s == index_series(code) and str(date.fromisoformat(d).year) in calendar.years]
        through = expected or (max(known_dates) if known_dates else None)
        try:
            rows = aligned_rows(latest, code, calendar, through) if through else []
        except CalendarUnknown as exc:
            rows = []
            warnings.append(str(exc))
        matched = [r for r in rows if r["spread_pp"] is not None]
        payload = {"schema_version": 1, "code": code, "name": name, "rows": rows}
        write_json(site_root / "data" / f"{code}.json", payload)
        atomic_text(site_root / "data" / f"{code}.csv", csv_text(rows))
        equity_dates = [d for (s, d) in latest if s == index_series(code)]
        bond_dates = [d for (s, d) in latest if s == BOND_SERIES]
        manifest["indexes"].append({"code": code, "name": name, "rows": len(rows), "matched_rows": len(matched),
                                    "first_date": matched[0]["trade_date"] if matched else None,
                                    "latest": matched[-1] if matched else None,
                                    "dividend_latest_date": max(equity_dates, default=None), "bond_latest_date": max(bond_dates, default=None),
                                    "missing_dates": [r["trade_date"] for r in rows if r["spread_pp"] is None]})
    write_json(site_root / "data/manifest.json", manifest)
    # 国债保留自己的原生观察日历，供研究下载；与 A 股匹配时另做同日内连接。
    bond_rows = sorted((r for (s, _), r in latest.items() if s == BOND_SERIES), key=lambda r: r["trade_date"])
    stream = StringIO(newline="")
    fields = ["trade_date", "value", "unit", "source_id", "definition_id", "source_published_at", "observed_at", "available_at", "revision", "payload_sha256", "source_url"]
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(bond_rows)
    atomic_text(site_root / "data/chinabond_cgb_10y.csv", "\ufeff" + stream.getvalue())
    return manifest

def backfill_bonds(start, end, data_root=ROOT / "data", fetcher=fetch_bond):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end or end > datetime.now(SH).date():
        raise SourceError("回补日期区间非法")
    report = {"started_at": utc_now(), "requested_start": str(start), "requested_end": str(end), "chunks": []}
    store = Store(data_root)
    with store.lock():
        while start <= end:
            stop = min(end, start + timedelta(days=364))
            item = {"start": str(start), "end": str(stop)}
            try:
                rows = fetcher(str(start), str(stop))
                item.update(store.merge(rows), first_date=min(r["trade_date"] for r in rows), last_date=max(r["trade_date"] for r in rows), fetched_rows=len(rows))
            except Exception as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
            report["chunks"].append(item)
            LOG.info("backfill %s", item)
            start = stop + timedelta(days=1)
        report["finished_at"] = utc_now()
        write_json(Path(data_root) / "backfill_status.json", report)
    return report
