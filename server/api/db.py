"""SQLite 存储：garments、outfits、jobs 三张表。JSON 字段以 TEXT 存储，同一连接 + 锁保证线程安全。"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _clean_text(value: str | None) -> str | None:
    """去掉孤立的 UTF-16 代理字符和不可打印的控制字符；清洗后为空则返回 None。"""
    if value is None:
        return None
    value = _SURROGATE_RE.sub("", value)
    value = _CONTROL_RE.sub("", value)
    value = value.strip()
    return value or None


def _clean_analysis(analysis: dict | None) -> dict | None:
    if not analysis:
        return analysis
    analysis = dict(analysis)
    if "color" in analysis:
        analysis["color"] = _clean_text(analysis["color"])
    if "note" in analysis:
        analysis["note"] = _clean_text(analysis["note"])
    return analysis


SCHEMA = """
CREATE TABLE IF NOT EXISTS garments (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    category TEXT,
    category_source TEXT,
    analysis TEXT,
    image TEXT NOT NULL,
    cutout TEXT,
    source TEXT NOT NULL,
    job_id TEXT,
    created_at TEXT NOT NULL,
    force_segment INTEGER NOT NULL DEFAULT 0,
    user_id TEXT NOT NULL DEFAULT 'local'
);
CREATE TABLE IF NOT EXISTS outfits (
    id TEXT PRIMARY KEY,
    preset_id TEXT NOT NULL,
    garment_ids TEXT NOT NULL,
    options TEXT NOT NULL,
    status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    job_id TEXT NOT NULL,
    result TEXT,
    turntable_status TEXT NOT NULL DEFAULT 'none',
    turntable_job_id TEXT,
    turntable_video TEXT,
    turntable_provider TEXT,
    turntable_error_code TEXT,
    turntable_error_message TEXT,
    turntable_duration INTEGER,
    created_at TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'local'
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    status TEXT NOT NULL,
    progress_done INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 1,
    progress_note TEXT NOT NULL DEFAULT '',
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'local'
);
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    rating INTEGER,
    text TEXT,
    created_at TEXT NOT NULL
);
"""


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self):
        """给早于 v1.2/v1.3 契约创建的旧数据库补列（CREATE TABLE IF NOT EXISTS 不会给已存在的表加新列）。"""
        garment_cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(garments)")}
        if "force_segment" not in garment_cols:
            self._conn.execute("ALTER TABLE garments ADD COLUMN force_segment INTEGER NOT NULL DEFAULT 0")
        if "user_id" not in garment_cols:
            # DEFAULT 'local' 对已有行同样生效，满足"旧数据归 local 用户"的要求
            self._conn.execute("ALTER TABLE garments ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'")
        outfit_cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(outfits)")}
        if "user_id" not in outfit_cols:
            self._conn.execute("ALTER TABLE outfits ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'")
        job_cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(jobs)")}
        if "user_id" not in job_cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'")

    def close(self):
        self._conn.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """只读用途：bench/usage_report.py 等内部工具复用同一个连接做聚合查询。"""
        return self._conn

    # ---------- 启动恢复 ----------
    def recover_running_jobs(self):
        """重启后把 running 状态的任务标记为失败（对应的 garment/outfit 也标记失败）。"""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM jobs WHERE status IN ('running','queued')").fetchall()
            for row in rows:
                self._conn.execute(
                    "UPDATE jobs SET status='failed', error_code=?, error_message=?, updated_at=? WHERE id=?",
                    ("interrupted", "服务重启，任务已中断", now_iso(), row["id"]))
                if row["kind"] in ("prepare_garment",):
                    self._conn.execute(
                        "UPDATE garments SET status='failed', error_code=?, error_message=? WHERE id=? AND status IN ('pending','processing')",
                        ("interrupted", "服务重启，任务已中断", row["target_id"]))
                else:
                    self._conn.execute(
                        "UPDATE outfits SET status='failed', error_code=?, error_message=? WHERE id=? AND status IN ('queued','running')",
                        ("interrupted", "服务重启，任务已中断", row["target_id"]))
                    self._conn.execute(
                        "UPDATE outfits SET turntable_status='failed', turntable_error_code=?, turntable_error_message=? "
                        "WHERE id=? AND turntable_status IN ('queued','running')",
                        ("interrupted", "服务重启，任务已中断", row["target_id"]))
            self._conn.commit()

    # ---------- garments ----------
    def create_garment(self, *, status: str, category: str | None, category_source: str | None,
                       image: dict, source: dict, user_id: str, job_id: str | None = None,
                       error_code: str | None = None, error_message: str | None = None) -> dict:
        gid = new_id()
        row = dict(id=gid, status=status, error_code=error_code, error_message=error_message,
                   category=category, category_source=category_source, analysis=None,
                   image=json.dumps(image), cutout=None, source=json.dumps(source), job_id=job_id,
                   created_at=now_iso(), user_id=user_id)
        with self._lock:
            self._conn.execute(
                "INSERT INTO garments (id, status, error_code, error_message, category, category_source, "
                "analysis, image, cutout, source, job_id, created_at, user_id) VALUES "
                "(:id,:status,:error_code,:error_message,:category,:category_source,:analysis,:image,:cutout,"
                ":source,:job_id,:created_at,:user_id)", row)
            self._conn.commit()
        return self.get_garment(gid)

    def get_garment(self, gid: str) -> dict | None:
        """不做用户过滤，仅供任务处理等受信内部代码使用；接口路由请用 get_garment_for_user。"""
        with self._lock:
            row = self._conn.execute("SELECT * FROM garments WHERE id=?", (gid,)).fetchone()
        return _garment_from_row(row) if row else None

    def get_garment_for_user(self, gid: str, user_id: str) -> dict | None:
        row = self.get_garment(gid)
        return row if row and row["user_id"] == user_id else None

    def list_garments(self, user_id: str, status: str | None = None, category: str | None = None) -> list[dict]:
        query = "SELECT * FROM garments WHERE user_id=?"
        params = [user_id]
        if status:
            query += " AND status=?"
            params.append(status)
        if category:
            query += " AND category=?"
            params.append(category)
        query += " ORDER BY created_at DESC, rowid DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_garment_from_row(r) for r in rows]

    def update_garment(self, gid: str, user_id: str | None = None, **fields):
        if not fields:
            return
        if "analysis" in fields:
            fields["analysis"] = _clean_analysis(fields["analysis"])
        json_cols = {"analysis", "image", "cutout", "source"}
        cols, params = [], []
        for k, v in fields.items():
            cols.append(f"{k}=?")
            params.append(json.dumps(v) if k in json_cols and v is not None else v)
        params.append(gid)
        query = f"UPDATE garments SET {', '.join(cols)} WHERE id=?"
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        with self._lock:
            self._conn.execute(query, params)
            self._conn.commit()

    def delete_garment(self, gid: str, user_id: str | None = None) -> bool:
        query = "DELETE FROM garments WHERE id=?"
        params = [gid]
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        with self._lock:
            cur = self._conn.execute(query, params)
            self._conn.commit()
        return cur.rowcount > 0

    # ---------- outfits ----------
    def create_outfit(self, *, preset_id: str, garment_ids: list[str], options: dict, job_id: str,
                      user_id: str) -> dict:
        oid = new_id()
        row = dict(id=oid, preset_id=preset_id, garment_ids=json.dumps(garment_ids), options=json.dumps(options),
                   status="queued", error_code=None, error_message=None, job_id=job_id, result=None,
                   turntable_status="none", turntable_job_id=None, turntable_video=None, turntable_provider=None,
                   turntable_error_code=None, turntable_error_message=None, turntable_duration=None,
                   created_at=now_iso(), user_id=user_id)
        with self._lock:
            self._conn.execute(
                "INSERT INTO outfits (id, preset_id, garment_ids, options, status, error_code, error_message, "
                "job_id, result, turntable_status, turntable_job_id, turntable_video, turntable_provider, "
                "turntable_error_code, turntable_error_message, turntable_duration, created_at, user_id) VALUES "
                "(:id,:preset_id,:garment_ids,:options,:status,:error_code,:error_message,:job_id,:result,"
                ":turntable_status,:turntable_job_id,:turntable_video,:turntable_provider,:turntable_error_code,"
                ":turntable_error_message,:turntable_duration,:created_at,:user_id)", row)
            self._conn.commit()
        return self.get_outfit(oid)

    def get_outfit(self, oid: str) -> dict | None:
        """不做用户过滤，仅供任务处理等受信内部代码使用；接口路由请用 get_outfit_for_user。"""
        with self._lock:
            row = self._conn.execute("SELECT * FROM outfits WHERE id=?", (oid,)).fetchone()
        return _outfit_from_row(row) if row else None

    def get_outfit_for_user(self, oid: str, user_id: str) -> dict | None:
        row = self.get_outfit(oid)
        return row if row and row["user_id"] == user_id else None

    def list_outfits(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM outfits WHERE user_id=? ORDER BY created_at DESC, rowid DESC", (user_id,)).fetchall()
        return [_outfit_from_row(r) for r in rows]

    def update_outfit(self, oid: str, user_id: str | None = None, **fields):
        if not fields:
            return
        json_cols = {"garment_ids", "options", "result", "turntable_video"}
        cols, params = [], []
        for k, v in fields.items():
            cols.append(f"{k}=?")
            params.append(json.dumps(v) if k in json_cols and v is not None else v)
        params.append(oid)
        query = f"UPDATE outfits SET {', '.join(cols)} WHERE id=?"
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        with self._lock:
            self._conn.execute(query, params)
            self._conn.commit()

    def delete_outfit(self, oid: str, user_id: str | None = None) -> bool:
        query = "DELETE FROM outfits WHERE id=?"
        params = [oid]
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        with self._lock:
            cur = self._conn.execute(query, params)
            self._conn.commit()
        return cur.rowcount > 0

    # ---------- jobs ----------
    def create_job(self, *, kind: str, target_id: str, user_id: str, total: int = 1) -> dict:
        jid = new_id()
        ts = now_iso()
        row = dict(id=jid, kind=kind, target_id=target_id, status="queued", progress_done=0,
                   progress_total=total, progress_note="", error_code=None, error_message=None,
                   created_at=ts, updated_at=ts, user_id=user_id)
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (id, kind, target_id, status, progress_done, progress_total, progress_note, "
                "error_code, error_message, created_at, updated_at, user_id) VALUES "
                "(:id,:kind,:target_id,:status,:progress_done,:progress_total,:progress_note,:error_code,"
                ":error_message,:created_at,:updated_at,:user_id)", row)
            self._conn.commit()
        return self.get_job(jid)

    def get_job(self, jid: str) -> dict | None:
        """不做用户过滤，仅供任务队列等受信内部代码使用；接口路由请用 get_job_for_user。"""
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(row) if row else None

    def get_job_for_user(self, jid: str, user_id: str) -> dict | None:
        row = self.get_job(jid)
        return row if row and row["user_id"] == user_id else None

    def update_job(self, jid: str, **fields):
        if not fields:
            return
        fields["updated_at"] = now_iso()
        cols = [f"{k}=?" for k in fields]
        params = list(fields.values()) + [jid]
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id=?", params)
            self._conn.commit()

    def reset_job_for_retry(self, jid: str):
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status='queued', progress_done=0, progress_total=1, progress_note='', "
                "error_code=NULL, error_message=NULL, updated_at=? WHERE id=?", (now_iso(), jid))
            self._conn.commit()

    # ---------- usage_events（v1.4 额度 + 报表） ----------
    def record_usage_event(self, user_id: str, kind: str, created_at: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO usage_events (user_id, kind, created_at) VALUES (?,?,?)",
                (user_id, kind, created_at or now_iso()))
            self._conn.commit()

    def count_usage_events(self, user_id: str, kinds: tuple[str, ...], since_iso: str) -> int:
        placeholders = ",".join("?" for _ in kinds)
        query = (f"SELECT COUNT(*) AS c FROM usage_events WHERE user_id=? AND kind IN ({placeholders}) "
                f"AND created_at>=?")
        with self._lock:
            row = self._conn.execute(query, (user_id, *kinds, since_iso)).fetchone()
        return row["c"]

    # ---------- feedback（v1.4） ----------
    def create_feedback(self, *, user_id: str, target_type: str, target_id: str | None,
                        rating: int | None, text: str | None) -> dict:
        fid = new_id()
        row = dict(id=fid, user_id=user_id, target_type=target_type, target_id=target_id,
                   rating=rating, text=text, created_at=now_iso())
        with self._lock:
            self._conn.execute(
                "INSERT INTO feedback (id, user_id, target_type, target_id, rating, text, created_at) VALUES "
                "(:id,:user_id,:target_type,:target_id,:rating,:text,:created_at)", row)
            self._conn.commit()
        return row


def _json_or_none(text):
    return json.loads(text) if text is not None else None


def _garment_from_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["analysis"] = _json_or_none(d["analysis"])
    d["image"] = _json_or_none(d["image"])
    d["cutout"] = _json_or_none(d["cutout"])
    d["source"] = _json_or_none(d["source"])
    return d


def _outfit_from_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["garment_ids"] = _json_or_none(d["garment_ids"]) or []
    d["options"] = _json_or_none(d["options"]) or {}
    d["result"] = _json_or_none(d["result"])
    d["turntable_video"] = _json_or_none(d["turntable_video"])
    return d
