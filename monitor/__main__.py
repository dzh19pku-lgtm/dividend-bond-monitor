import argparse
import json
import logging
from pathlib import Path
from .config import ROOT, INDEXES
from .pipeline import update, build, backfill_bonds
from .sources import parse_csi, utc_now
from .store import Store
from .calendar_refresh import refresh_calendar

def main():
    parser = argparse.ArgumentParser(description="红利股债差：采集、回补、PIT 导出与静态构建")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("update")
    collect.add_argument("--bootstrap", action="store_true", help="首次建库：休市或盘中也取最近已收盘数据")
    render = sub.add_parser("build")
    render.add_argument("--output", type=Path, default=ROOT / "site")
    render.add_argument("--as-of", help="时区时间戳；只使用该时刻之前实际采集到的版本")
    backfill = sub.add_parser("backfill-bonds")
    backfill.add_argument("--start", required=True)
    backfill.add_argument("--end", required=True)
    ingest = sub.add_parser("import-csi")
    ingest.add_argument("--file", type=Path, required=True)
    ingest.add_argument("--code", choices=INDEXES, required=True)
    sub.add_parser("refresh-calendar", help="从上交所核验当前/下一年休市表；异常保留原日历")
    review = sub.add_parser("accept-quarantine", help="人工确认原始数据后接纳隔离值；可用时间为确认时刻")
    review.add_argument("--series", required=True)
    review.add_argument("--date", required=True)
    review.add_argument("--value", type=float, required=True)
    review.add_argument("--reason", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "update":
        result = update(args.data_dir, bootstrap=args.bootstrap)
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result["state"] in ("current", "skipped_non_session_or_before_close") else 2
    if args.command == "build":
        result = build(args.data_dir, args.output, as_of=args.as_of)
        print(json.dumps({"indexes": [{k: v for k, v in x.items() if k != "latest"} for x in result["indexes"]], "warnings": result["warnings"]}, ensure_ascii=True))
    elif args.command == "backfill-bonds":
        report = backfill_bonds(args.start, args.end, args.data_dir)
        print(json.dumps(report, ensure_ascii=True))
        return 2 if any("error" in x for x in report["chunks"]) else 0
    elif args.command == "import-csi":
        rows = parse_csi(args.file.read_bytes(), args.code, utc_now())
        store = Store(args.data_dir)
        with store.lock():
            print(store.merge(rows))
    elif args.command == "refresh-calendar":
        with Store(args.data_dir).lock():
            result = refresh_calendar(args.data_dir, force=True)
        print(json.dumps(result, ensure_ascii=True))
        return 2 if result["state"] == "error" else 0
    elif args.command == "accept-quarantine":
        store = Store(args.data_dir)
        with store.lock():
            print(store.accept_quarantined(args.series,args.date,args.value,args.reason))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
