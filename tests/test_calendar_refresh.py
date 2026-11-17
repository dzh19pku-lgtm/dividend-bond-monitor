from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import json
from monitor.calendar_refresh import parse_calendar, refresh_calendar
from monitor.config import ROOT
from monitor.sources import SourceError


class CalendarRefreshTests(TestCase):
    def setUp(self):
        self.payload=(ROOT/"tests/fixtures/sse-calendar-2026.html").read_bytes()
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        original=json.loads((ROOT/"data/calendar.json").read_text(encoding="utf-8"))
        original["years"]={"2026":original["years"]["2026"]}
        (self.root/"calendar.json").write_text(json.dumps(original),encoding="utf-8")
        self.now=datetime(2026,11,17,tzinfo=timezone.utc)

    def test_real_official_table_matches_checked_calendar(self):
        year, spec=parse_calendar(self.payload)
        known=json.loads((self.root/"calendar.json").read_text(encoding="utf-8"))
        self.assertEqual(year,"2026")
        self.assertEqual(spec["closures"],known["years"][year]["closures"])

    def test_incomplete_table_rejected(self):
        with self.assertRaises(SourceError):
            parse_calendar(self.payload.replace("国庆节".encode(),b"unknown"))

    def test_failure_preserves_existing_calendar_and_checks_once_a_day(self):
        before=(self.root/"calendar.json").read_bytes()
        fetch=mock.Mock(side_effect=SourceError("offline"))
        result=refresh_calendar(self.root,self.now,fetcher=fetch)
        self.assertEqual(result["state"],"error")
        refresh_calendar(self.root,self.now,fetcher=fetch)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(before,(self.root/"calendar.json").read_bytes())

    def test_changed_holiday_requires_review(self):
        payload=self.payload.replace("2月23日".encode(),"2月22日".encode())
        before=(self.root/"calendar.json").read_bytes()
        result=refresh_calendar(self.root,self.now,fetcher=lambda _:mock.Mock(content=payload))
        self.assertEqual(result["state"],"error")
        self.assertTrue(result["requires_review"])
        self.assertEqual(before,(self.root/"calendar.json").read_bytes())

    def test_add_new_year_only_after_validated_table(self):
        # 合成下一年表只验证新增机制，不作为真实 2027 年日历写入项目。
        payload=self.payload.replace(b"2026",b"2027")
        result=refresh_calendar(self.root,self.now,fetcher=lambda _:mock.Mock(content=payload))
        self.assertEqual(result["state"],"added")
        years=json.loads((self.root/"calendar.json").read_text(encoding="utf-8"))["years"]
        self.assertIn("2026",years);self.assertIn("2027",years)
