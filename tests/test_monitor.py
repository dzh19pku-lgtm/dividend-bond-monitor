"""合成数据仅用于隔离测试；生产目录不会写入测试值。"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import csv
import io
import json
import unittest
import requests
import pandas as pd
from monitor.calendar import TradingCalendar, CalendarUnknown, SH
from monitor.sources import parse_csi, parse_bond, percent, get, SourceError, observation
from monitor.config import ROOT, DEFINITION, BOND_DEFINITION, BOND_SERIES, INDEXES, index_series
from monitor.store import Store, write_json
from monitor.analytics import aligned_rows, features
from monitor.pipeline import update, build, csv_text, backfill_bonds

TS = "2026-11-16T12:00:00+00:00"

def obs(code="000922", day="2026-11-16", value=4.0, ts=TS):
    bond=code=="bond"
    return observation(BOND_SERIES if bond else index_series(code),"chinabond_official" if bond else "csindex_official",
                       BOND_DEFINITION if bond else DEFINITION,day,value,ts,"https://example.invalid/test","a"*64)

def csi_frame():
    return pd.DataFrame({"日期Date":["20261116"],"指数代码Index Code":["000922"],"股息率1（总股本）D/P1":["4.49"],"股息率2（计算用股本）D/P2":["4.23"]})

class SourceTests(TestCase):
    def test_csi_schema_and_value(self):
        with mock.patch("monitor.sources.pd.read_excel",return_value=csi_frame()):
            result=parse_csi(bytes.fromhex("D0CF11E0"),"000922",TS)
        self.assertEqual(result[0]["value"],4.23)
        self.assertEqual(result[0]["dp1_percent"],4.49)
        self.assertEqual(result[0]["trade_date"],"2026-11-16")
        self.assertIsNone(result[0]["source_published_at"])

    def test_missing_field_wrong_code_duplicate_date(self):
        bad=csi_frame().drop(columns=["股息率2（计算用股本）D/P2"])
        for frame in [bad,csi_frame().assign(**{"指数代码Index Code":["000300"]}),pd.concat([csi_frame(),csi_frame()])]:
            with self.subTest(columns=list(frame.columns)),mock.patch("monitor.sources.pd.read_excel",return_value=frame),self.assertRaises(SourceError):
                parse_csi(bytes.fromhex("D0CF11E0"),"000922",TS)

    def test_html_error_instead_of_excel(self):
        with self.assertRaises(SourceError):parse_csi(b"<html>503</html>","000922",TS)

    def test_unit_bounds_and_nonfinite(self):
        for value in [float("nan"),float("inf"),-1,400,True,"--"]:
            with self.subTest(value=value),self.assertRaises(SourceError):percent(value,20)
        with self.assertRaises(SourceError):percent(.04,20,unit="fraction")

    def test_bond_curve_filter(self):
        frame=pd.DataFrame({"曲线名称":["中债国债收益率曲线","中债商业银行普通债收益率曲线(AAA)"],"日期":["2026-11-16"]*2,"10年":[1.6285,4.5]})
        result=parse_bond(frame.to_html(index=False).encode(),"2026-11-16","2026-11-16",TS)
        self.assertEqual(len(result),1);self.assertEqual(result[0]["value"],1.6285)

    def test_bond_wrong_date_empty_missing(self):
        for frame in [pd.DataFrame({"日期":["2026-11-16"],"10年":[1.5]}),pd.DataFrame({"曲线名称":["中债国债收益率曲线"],"日期":["2026-11-15"],"10年":[1.5]})]:
            with self.assertRaises(SourceError):parse_bond(frame.to_html(index=False).encode(),"2026-11-16","2026-11-16",TS)

    def test_transient_timeout_retry(self):
        response=mock.Mock(content=b"valid");response.raise_for_status.return_value=None
        client=mock.Mock();client.get.side_effect=[requests.Timeout(),response]
        self.assertIs(get("https://example.invalid",session=client,sleep=lambda _:None),response)
        self.assertEqual(client.get.call_count,2)

    def test_permanent_error_no_retry(self):
        response=mock.Mock(status_code=403)
        client=mock.Mock();client.get.side_effect=requests.HTTPError(response=response)
        with self.assertRaises(SourceError):get("https://example.invalid",session=client,sleep=lambda _:None)
        self.assertEqual(client.get.call_count,1)

class CalendarTests(TestCase):
    def setUp(self):self.cal=TradingCalendar()
    def test_holidays_weekend_and_makeup_workday(self):
        for d in ["2026-02-16","2026-02-23","2026-10-01","2026-10-10","2026-11-15"]:self.assertFalse(self.cal.is_session(d))
        self.assertTrue(self.cal.is_session("2026-02-24"))
    def test_unknown_year_fails(self):
        with self.assertRaises(CalendarUnknown):self.cal.is_session("2099-01-05")
    def test_last_close_and_holiday_next_open(self):
        self.assertEqual(self.cal.expected_date(datetime(2026,11,17,10,tzinfo=SH)),"2026-11-16")
        self.assertEqual(self.cal.expected_date(datetime(2026,11,17,19,tzinfo=SH)),"2026-11-17")
        self.assertEqual(str(self.cal.next_session("2026-09-30")),"2026-10-08")
    def test_late_observation_never_assigned_past_open(self):
        self.assertEqual(self.cal.usable_open("2026-11-16","2026-11-17T10:00:00+08:00"),"2026-11-18T09:30:00+08:00")

class StoreTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name);self.store=Store(self.root)
    def tearDown(self):self.temp.cleanup()
    def test_idempotency_first_seen_and_revisions(self):
        self.assertEqual(self.store.merge([obs()])["added"],1)
        self.assertEqual(self.store.merge([obs(ts="2026-11-16T13:00:00+00:00")])["added"],0)
        self.store.merge([obs(value=4.1,ts="2026-11-17T12:00:00+00:00")])
        key=(index_series("000922"),"2026-11-16")
        self.assertEqual(self.store.latest(as_of=TS)[key]["value"],4)
        self.assertEqual(self.store.latest()[key]["revision"],2)
        self.assertEqual(self.store.latest()[key]["first_observed_at"],TS)
    def test_jump_quarantine_preserves_valid_value(self):
        self.store.merge([obs()]);result=self.store.merge([obs(value=.04,ts="2026-11-17T12:00:00+00:00")])
        self.assertEqual(result["quarantined"],1);self.assertEqual(next(iter(self.store.latest().values()))["value"],4)
    def test_reviewed_jump_is_available_only_after_review(self):
        self.store.merge([obs()]);self.store.merge([obs(value=6,ts="2026-11-17T03:00:00+00:00")])
        self.store.accept_quarantined(index_series("000922"),"2026-11-16",6,"test: confirmed original response",now="2026-11-17T04:00:00+00:00")
        key=(index_series("000922"),"2026-11-16")
        self.assertEqual(self.store.latest(as_of="2026-11-17T03:30:00+00:00")[key]["value"],4)
        self.assertEqual(self.store.latest()[key]["value"],6)
    def test_schema_error_preserves_history(self):
        self.store.merge([obs()]);bad=dict(obs(),unit="fraction")
        with self.assertRaises(SourceError):self.store.merge([bad])
        self.assertEqual(len(self.store.events()),1)
    def test_corrupt_history_fails_closed(self):
        self.store.merge([obs()]);path=next(self.root.glob("observations/*/*.jsonl"));path.write_text("not-json\n",encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):self.store.merge([obs()])
        self.assertEqual(path.read_text(encoding="utf-8"),"not-json\n")
    def test_concurrent_update_excluded(self):
        with self.store.lock():
            with self.assertRaises(FileExistsError):
                with self.store.lock():pass

class PipelineTests(TestCase):
    def setUp(self):
        calendar_refresh=mock.patch("monitor.pipeline.refresh_calendar", return_value={"state":"unchanged"})
        calendar_refresh.start();self.addCleanup(calendar_refresh.stop)
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name);self.data=self.root/"data";self.data.mkdir()
        (self.data/"calendar.json").write_text((ROOT/"data/calendar.json").read_text(encoding="utf-8"),encoding="utf-8")
    def tearDown(self):self.temp.cleanup()
    def test_success_and_repeat(self):
        kwargs=dict(data_root=self.data,now=datetime(2026,11,16,20,tzinfo=SH),equity_fetch=lambda c:[obs(c)],bond_fetch=lambda a,b:[obs("bond",value=1.6)])
        self.assertEqual(update(**kwargs)["state"],"current")
        self.assertEqual(sum(s["added"] for s in update(**kwargs)["sources"].values()),0)
        self.assertEqual(len(Store(self.data).events()),5)
    def test_failure_does_not_destroy_history(self):
        Store(self.data).merge([obs()]);broken=lambda *a:(_ for _ in ()).throw(SourceError("offline"))
        with self.assertLogs("monitor.pipeline", level="ERROR"):
            result=update(self.data,now=datetime(2026,11,16,20,tzinfo=SH),equity_fetch=broken,bond_fetch=broken)
        self.assertEqual(result["state"],"degraded");self.assertEqual(len(Store(self.data).events()),1)
    def test_skips_holiday(self):
        fetch=mock.Mock(side_effect=AssertionError("should not fetch"))
        result=update(self.data,now=datetime(2026,10,1,20,tzinfo=SH),equity_fetch=fetch,bond_fetch=fetch)
        self.assertEqual(result["state"],"skipped_non_session_or_before_close");fetch.assert_not_called()
    def test_date_mismatch_has_no_spread_or_forward_fill(self):
        Store(self.data).merge([obs(day="2026-11-13"),obs("bond",value=1.6)])
        manifest=build(self.data,self.root/"site",now=datetime(2026,11,16,20,tzinfo=SH))
        self.assertIsNone(manifest["indexes"][0]["latest"])
        rows=json.loads((self.root/"site/data/000922.json").read_text(encoding="utf-8"))["rows"]
        self.assertTrue(all(r["spread_pp"] is None for r in rows))
    def test_csv_frontend_and_backfill_timestamp(self):
        Store(self.data).merge([obs(ts="2026-11-17T03:00:00+00:00"),obs("bond",value=1.6,ts="2026-11-17T03:00:00+00:00")])
        result=build(self.data,self.root/"site",now=datetime(2026,11,17,12,tzinfo=SH))
        row=result["indexes"][0]["latest"]
        self.assertFalse(row["tplus1_ready"]);self.assertIsNone(row["mean_252"])
        exported=list(csv.DictReader(io.StringIO(csv_text([row]).lstrip("\ufeff"))))
        self.assertEqual(float(exported[0]["spread_pp"]),2.4)
        self.assertTrue((self.root/"site/data/manifest.json").exists())
        historical=build(self.data,self.root/"past",as_of=TS)
        self.assertIsNone(historical["indexes"][0]["latest"])
    def test_backfill_preserves_actual_observation_time(self):
        result=backfill_bonds("2026-11-13","2026-11-16",self.data,fetcher=lambda a,b:[obs("bond",day="2026-11-13",value=1.6)])
        self.assertEqual(result["chunks"][0]["added"],1)
        row=Store(self.data).events()[0];self.assertEqual(row["available_at"],TS)

class StatisticsTests(TestCase):
    def setUp(self):
        # 测试专用交易日历；不写入生产日历。
        self.cal=TradingCalendar(payload={"years":{str(y):{"closures":[]} for y in range(2020,2025)}})
        dates=self.cal.sessions("2020-01-01","2023-12-29")
        self.rows=[dict(trade_date=d,spread_pp=1+i*.001,available_at=d+"T12:00:00+00:00") for i,d in enumerate(dates)]
    def test_warmup_statistics_and_zero_variance(self):
        rows=features(self.rows[:300],self.cal)
        self.assertIsNone(rows[250]["mean_252"]);self.assertAlmostEqual(rows[251]["mean_252"],1.1255)
        self.assertIsNone(rows[-1]["mean_756"])
        flat=[dict(r,spread_pp=1) for r in self.rows[:252]]
        self.assertIsNone(features(flat,self.cal)[-1]["zscore_252"])
    def test_future_data_does_not_change_past_statistics(self):
        first=features(self.rows[:300],self.cal)
        changed=self.rows[:300]+[dict(r,spread_pp=100) for r in self.rows[300:]]
        self.assertEqual(first,features(changed,self.cal)[:300])
    def test_missing_session_breaks_window(self):
        rows=[dict(r) for r in self.rows[:260]];rows[100]["spread_pp"]=None;rows[100]["available_at"]=None
        self.assertIsNone(features(rows,self.cal)[-1]["zscore_252"])

if __name__=="__main__":unittest.main()
