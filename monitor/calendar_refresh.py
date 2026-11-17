"""读取上交所年度休市表；格式或已有日历变化时保留旧版并要求核验。"""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from lxml import html
from .sources import get, SourceError, utc_now
from .store import write_json

URL = "https://www.sse.com.cn/disclosure/dealinstruc/closed/"
HOLIDAYS = {"元旦", "春节", "清明节", "劳动节", "端午节", "中秋节", "国庆节"}

class CalendarConflict(SourceError):
    pass


def parse_calendar(payload):
    tree = html.fromstring(payload.decode("utf-8"))
    headings = [n for n in tree.xpath("//strong") if re.fullmatch(r"\s*20\d{2}年休市安排\s*", n.text_content())]
    if len(headings) != 1:
        raise SourceError("上交所年度休市标题不唯一或格式改变")
    year = int(headings[0].text_content().strip()[:4])
    tables = headings[0].xpath("following::table[1]")
    if not tables:
        raise SourceError("上交所休市表缺失")
    closures, labels = [], set()
    # 只解析明确列出的休市区间，不把后面的补班周末当交易日。
    pattern = re.compile(r"^(\d{1,2})月(\d{1,2})日(?:（[^）]+）)?(?:至(\d{1,2})月(\d{1,2})日(?:（[^）]+）)?)?休市[，,]")
    for row in tables[0].xpath(".//tr"):
        cells = row.xpath("./td")
        if len(cells) != 2:
            raise SourceError("上交所休市表列数改变")
        label = cells[0].text_content().strip().rstrip("：:")
        text = re.sub(r"\s+", "", cells[1].text_content())
        match = pattern.match(text)
        if label not in HOLIDAYS or label in labels or not match:
            raise SourceError("休市假日或日期格式待人工核验")
        labels.add(label)
        m1, d1, m2, d2 = match.groups()
        start = date(year, int(m1), int(d1))
        end = date(year, int(m2 or m1), int(d2 or d1))
        if not 0 <= (end - start).days <= 20:
            raise SourceError("休市区间越界")
        closures.append([str(start), str(end)])
    if labels != HOLIDAYS:
        raise SourceError("年度休市表不完整或合并假日格式待核验")
    closures.sort()
    if any(a[1] >= b[0] for a, b in zip(closures, closures[1:])):
        raise SourceError("休市区间重叠")
    return str(year), {"closures": closures, "source": URL, "payload_sha256": hashlib.sha256(payload).hexdigest()}


def refresh_calendar(data_root, now=None, force=False, fetcher=get):
    data_root = Path(data_root)
    now = now or datetime.now(timezone.utc)
    path = data_root / "calendar.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    previous_path = data_root / "calendar_refresh.json"
    today = now.date().isoformat()
    if not force and previous_path.exists():
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        if previous.get("checked_on") == today:
            return previous
    report = {"checked_on": today, "source": URL, "state": "error"}
    try:
        response = fetcher(URL)
        year, spec = parse_calendar(response.content)
        if int(year) not in (now.year, now.year + 1):
            raise SourceError("页面年份不是当前年或下一年")
        existing = original["years"].get(year)
        if existing is not None and existing.get("closures") != spec["closures"]:
            raise CalendarConflict("官网与已核验日历不一致，保留旧版并要求人工核验")
        if existing is None:
            original["years"][year] = spec
            original["verified_on"] = today
            write_json(path, original)
        report.update(state="unchanged" if existing else "added", page_year=year, payload_sha256=spec["payload_sha256"])
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["requires_review"] = isinstance(exc, CalendarConflict)
    report["finished_at"] = utc_now()
    write_json(previous_path, report)
    return report
