"""按序列/年份存储版本事件；相同值重复采集幂等，修订保留旧版本。"""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import os
import re
from .sources import SourceError, percent

def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)

def write_json(path, obj):
    atomic_text(path, json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")

class Store:
    def __init__(self, root):
        self.root = Path(root)

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / ".update.lock"
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(descriptor, str(os.getpid()).encode())
            yield
        finally:
            os.close(descriptor)
            path.unlink()

    def events(self, series=None):
        if series and not re.fullmatch(r"[a-z0-9_]+", series):
            raise SourceError("非法序列 ID")
        folder = self.root / "observations"
        paths = sorted((folder / series).glob("*.jsonl")) if series else sorted(folder.glob("*/*.jsonl"))
        records = []
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line:
                    record = json.loads(line)  # 损坏时显式失败，不当成空历史覆盖。
                    self.validate(record)
                    records.append(record)
        return records

    @staticmethod
    def validate(row):
        from .config import BOND_SERIES, BOND_DEFINITION, DEFINITION, INDEXES, index_series
        definitions = {index_series(c): ("csindex_official", DEFINITION) for c in INDEXES}
        definitions[BOND_SERIES] = ("chinabond_official", BOND_DEFINITION)
        expected = definitions.get(row.get("series_id"))
        if not expected or expected != (row.get("source_id"), row.get("definition_id")):
            raise SourceError("来源/定义与序列不一致")
        percent(row["value"], 15 if row["series_id"] == BOND_SERIES else 20, row["unit"])
        observed = datetime.fromisoformat(row["observed_at"])
        available = datetime.fromisoformat(row["available_at"])
        trade = datetime.strptime(row["trade_date"], "%Y-%m-%d").date()
        if observed.tzinfo is None or available.tzinfo is None or available < observed or trade > observed.astimezone(timezone(timedelta(hours=8))).date():
            raise SourceError("数据时间戳不合法")
        if not re.fullmatch(r"[0-9a-f]{64}", row["payload_sha256"]):
            raise SourceError("缺少原始响应指纹")

    def latest(self, series=None, as_of=None):
        result = {}
        for row in self.events(series):
            if as_of and datetime.fromisoformat(row["available_at"]) > datetime.fromisoformat(as_of):
                continue
            key = (row["series_id"], row["trade_date"])
            if key not in result or (datetime.fromisoformat(row["available_at"]), row.get("revision", 1)) > (datetime.fromisoformat(result[key]["available_at"]), result[key].get("revision", 1)):
                result[key] = row
        return result

    def merge(self, incoming, reviewed_jump=False):
        incoming = list(incoming)
        for row in incoming:
            self.validate(row)
        existing = self.latest()
        groups, added, quarantined = {}, 0, []
        for row in sorted(incoming, key=lambda r: (r["trade_date"], r["series_id"])):
            key = (row["series_id"], row["trade_date"])
            old = existing.get(key)
            if old and old["value"] == row["value"] and old.get("dp1_percent") == row.get("dp1_percent"):
                continue
            if old and datetime.fromisoformat(row["observed_at"]) < datetime.fromisoformat(old["observed_at"]):
                raise SourceError("旧采集记录不能覆盖较新版本")
            prior = [r for (s, d), r in existing.items() if s == row["series_id"] and d < row["trade_date"]]
            reference = old or (max(prior, key=lambda r: r["trade_date"]) if prior else None)
            if reference:
                jump = abs(row["value"] - reference["value"])
                ratio = (row["value"] / reference["value"]) if reference["value"] else 1
                if not reviewed_jump and (jump > 1.0 or (jump > 0.5 and (ratio < 0.5 or ratio > 2))):
                    quarantined.append(dict(row, reason="large_jump_requires_review", reference_value=reference["value"]))
                    continue
            saved = dict(row, revision=old.get("revision", 1) + 1 if old else 1,
                         first_observed_at=old["first_observed_at"] if old else row["observed_at"])
            path = self.root / "observations" / row["series_id"] / f'{row["trade_date"][:4]}.jsonl'
            groups.setdefault(path, []).append(saved)
            existing[key] = saved
            added += 1
        for path, records in groups.items():
            original = path.read_text(encoding="utf-8") if path.exists() else ""
            atomic_text(path, original + "".join(json.dumps(r, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n" for r in records))
        if quarantined:
            path = self.root / "quarantine.json"
            previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            keyed = {(r["series_id"], r["trade_date"], r["value"]): r for r in previous}
            for row in quarantined:
                keyed.setdefault((row["series_id"], row["trade_date"], row["value"]), row)
            write_json(path, list(keyed.values()))
        return {"added": added, "quarantined": len(quarantined)}

    def accept_quarantined(self, series, day, value, reason, now=None):
        """仅用于用户核对源文件后的显式操作；审核时间成为新的可用时间。"""
        if not reason.strip():
            raise SourceError("必须填写人工核验依据")
        path = self.root / "quarantine.json"
        candidates = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        matches = [r for r in candidates if (r["series_id"],r["trade_date"],r["value"]) == (series,day,value)]
        if len(matches) != 1:
            raise SourceError("未找到唯一隔离记录")
        reviewed_at = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
        row = dict(matches[0], available_at=reviewed_at, reviewed_at=reviewed_at, review_reason=reason)
        # 不修改原观察时间；晚获得的人工确认不能倒填为旧时点可用。
        return self.merge([row], reviewed_jump=True)
