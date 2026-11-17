"""严格解析已实测公开源；禁止用备用曲线静默替代中债国债。"""
from datetime import datetime, timezone, date, timedelta
from io import BytesIO, StringIO
import hashlib
import math
import time
import requests
import pandas as pd
from .config import CSI_URL, BOND_URL, BOND_SERIES, DEFINITION, BOND_DEFINITION, index_series

class SourceError(ValueError):
    pass

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def get(url, params=None, attempts=3, session=None, sleep=time.sleep):
    client = session or requests
    for attempt in range(attempts):
        try:
            r = client.get(url, params=params, timeout=(10, 30), headers={"User-Agent": "DividendBondMonitor/1.0 (public research; daily fetch)"})
            r.raise_for_status()
            if len(r.content) > 8_000_000:
                raise SourceError("响应超过大小限制")
            return r
        except requests.RequestException as exc:
            # 权限拒绝不重试；超时、限流和暂时性 5xx 才进行有界重试。
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status and status < 500 and status not in (408, 429):
                raise SourceError(f"HTTP {status}: {url}") from exc
            if attempt + 1 == attempts:
                raise SourceError(f"{type(exc).__name__}: {url}") from exc
            sleep(2 ** attempt)
    raise SourceError("请求未完成")

def percent(value, maximum, unit="percent"):
    if unit != "percent":
        raise SourceError(f"不支持的单位 {unit}，必须显式换算并提供口径")
    if isinstance(value, bool):
        raise SourceError("布尔值不是收益率")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SourceError(f"非法数值: {value!r}") from exc
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise SourceError(f"百分数越界: {value!r}")
    return number

def observation(series, source, definition, day, value, timestamp, url, digest, **extra):
    day = date.fromisoformat(str(day))
    ts = datetime.fromisoformat(timestamp)
    if ts.tzinfo is None or day > ts.astimezone(timezone(timedelta(hours=8))).date():
        raise SourceError("无时区采集时间或未来归属日期")
    return dict(schema_version=1, series_id=series, source_id=source, definition_id=definition,
                trade_date=day.isoformat(), value=value, unit="percent", source_published_at=None,
                observed_at=timestamp, available_at=timestamp, source_url=url, payload_sha256=digest,
                publication_time_status="unknown", **extra)

def parse_csi(payload, code, observed_at, url=None):
    if not payload.startswith(bytes.fromhex("D0CF11E0")):
        raise SourceError("官方 .xls 不是预期的 Excel 二进制文件（可能为错误网页）")
    frame = pd.read_excel(BytesIO(payload), dtype=str, engine="xlrd")
    required = {"日期Date", "指数代码Index Code", "股息率1（总股本）D/P1", "股息率2（计算用股本）D/P2"}
    if not required.issubset(frame.columns) or frame.empty:
        raise SourceError(f"中证字段缺失或空表: {list(frame.columns)}")
    result, dates = [], set()
    digest = hashlib.sha256(payload).hexdigest()
    for _, row in frame.iterrows():
        if str(row["指数代码Index Code"]).zfill(6) != code:
            raise SourceError("指数代码与请求不一致")
        try:
            day = datetime.strptime(row["日期Date"], "%Y%m%d").date()
        except (TypeError, ValueError) as exc:
            raise SourceError("非法中证日期") from exc
        if day in dates:
            raise SourceError("响应中出现重复日期")
        dates.add(day)
        result.append(observation(index_series(code), "csindex_official", DEFINITION, day,
            percent(row["股息率2（计算用股本）D/P2"], 20), observed_at, url or CSI_URL.format(code=code), digest,
            dp1_percent=percent(row["股息率1（总股本）D/P1"], 20), dividend_basis="official_dp2_not_verified_ttm"))
    return sorted(result, key=lambda x: x["trade_date"])

def fetch_csi(code):
    url = CSI_URL.format(code=code)
    response = get(url)
    # 成功收完响应后打时间戳，不能把请求开始时间当作已获得数据时间。
    return parse_csi(response.content, code, utc_now(), url)

def parse_bond(payload, start, end, observed_at, url=BOND_URL):
    try:
        tables = pd.read_html(StringIO(payload.decode("utf-8")), header=0)
    except (ValueError, UnicodeError) as exc:
        raise SourceError("中债响应不是有效数据表") from exc
    matches = [t for t in tables if {"曲线名称", "日期", "10年"}.issubset(t.columns)]
    if len(matches) != 1:
        raise SourceError("中债字段缺失或数据表不唯一")
    frame = matches[0]
    # 接口返回所有曲线，按全名筛选，禁止把银行债/中短票误当成国债。
    frame = frame[frame["曲线名称"] == "中债国债收益率曲线"]
    if frame.empty:
        raise SourceError("所请求区间无中债国债曲线数据")
    digest, result, dates = hashlib.sha256(payload).hexdigest(), [], set()
    for _, row in frame.iterrows():
        day = date.fromisoformat(str(row["日期"]))
        if not start <= day.isoformat() <= end or day in dates:
            raise SourceError("中债日期越界或重复")
        dates.add(day)
        result.append(observation(BOND_SERIES, "chinabond_official", BOND_DEFINITION, day,
            percent(row["10年"], 15), observed_at, url, digest, tenor_years=10, curve_type="yield_to_maturity"))
    return sorted(result, key=lambda x: x["trade_date"])

def fetch_bond(start, end):
    if (date.fromisoformat(end) - date.fromisoformat(start)).days not in range(366):
        raise SourceError("单次中债区间必须为 0 至 365 天")
    response = get(BOND_URL, params={"startDate": start, "endDate": end, "gjqx": "0", "qxId": "hzsylqx", "locale": "cn_ZH"})
    return parse_bond(response.content, start, end, utc_now(), response.url)
