"""사용자 데이터를 SQLite(data/gradepath.db)에 저장하고 불러옵니다.

사용자 구분 방식은 이전과 같습니다. 처음 접속한 브라우저에 무작위 사용자 번호(uid)를 쿠키로 심고,
DB에서는 그 uid별로 행을 나눠 저장합니다. 로그인은 없습니다.

바깥(app.py)에서 쓰는 함수는 JSON 시절과 똑같습니다: load(uid), save(uid, data), new_id(), new_uid(), valid_uid().
서버가 시작될 때 init()이 테이블을 만들고, 예전 JSON 파일(data/users/*.json)을 한 번만 옮겨 옵니다.
"""
import glob
import json
import os
import re
import sqlite3
import sys
import threading
import uuid

from rules import DEFAULT_SETTINGS

# 배포할 때 POLARIS_DATA_DIR로 영구 저장 디스크 위치를 지정할 수 있습니다 (기본: 이 폴더의 data)
BASE_DIR = os.environ.get("POLARIS_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(BASE_DIR, "gradepath.db")
JSON_DIR = os.path.join(BASE_DIR, "users")          # 예전 JSON 저장 위치 (이전 후에도 삭제하지 않음)
UID_RE = re.compile(r"[0-9a-f]{32}")                # 쿠키 값 형식 검사
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    uid        TEXT PRIMARY KEY,
    onboarded  INTEGER NOT NULL DEFAULT 0,
    settings_done INTEGER NOT NULL DEFAULT 0     -- 학사 설정을 직접 저장한 적이 있는지
);

CREATE TABLE IF NOT EXISTS settings (
    uid                      TEXT PRIMARY KEY REFERENCES users(uid) ON DELETE CASCADE,
    total_credits_required   INTEGER NOT NULL,
    major_credits_required   INTEGER NOT NULL,
    max_credits_per_semester INTEGER NOT NULL,
    max_credits_per_year     INTEGER NOT NULL DEFAULT 37,
    remaining_semesters      INTEGER NOT NULL,
    extra_semesters          INTEGER NOT NULL DEFAULT 0,
    seasonal_plan_credits    INTEGER NOT NULL,
    target_gpa               REAL    NOT NULL,
    mode                     TEXT    NOT NULL,
    retake_cap               TEXT    NOT NULL,
    retake_max_prior         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS completed_courses (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,      -- 입력 순서 유지용
    uid       TEXT    NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    id        TEXT    NOT NULL,
    semester  TEXT    NOT NULL,
    name      TEXT    NOT NULL,
    credit    INTEGER NOT NULL CHECK (credit BETWEEN 1 AND 6),
    type      TEXT    NOT NULL CHECK (type IN ('major', 'lib')),
    required  INTEGER NOT NULL DEFAULT 0,
    grade     TEXT    NOT NULL,
    UNIQUE (uid, id)
);

CREATE TABLE IF NOT EXISTS current_courses (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    uid       TEXT    NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    id        TEXT    NOT NULL,
    name      TEXT    NOT NULL,
    credit    INTEGER NOT NULL CHECK (credit BETWEEN 1 AND 6),
    type      TEXT    NOT NULL CHECK (type IN ('major', 'lib')),
    required  INTEGER NOT NULL DEFAULT 0,
    score     REAL    NOT NULL,
    mean      REAL    NOT NULL,
    std       REAL    NOT NULL,
    grading   TEXT    NOT NULL,
    exam_ratio REAL,
    att_score  REAL,
    att_ratio  REAL,
    asg_score  REAL,
    asg_ratio  REAL,
    fin_score  REAL,
    fin_ratio  REAL,
    items_json TEXT,
    max_score  REAL,
    fin_max    REAL,
    UNIQUE (uid, id)
);

-- JSON -> SQLite 이전을 끝낸 파일 기록 (같은 파일을 두 번 옮기지 않기 위함)
CREATE TABLE IF NOT EXISTS migrated_files (
    filename    TEXT PRIMARY KEY,
    result      TEXT NOT NULL,
    migrated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

SETTING_KEYS = list(DEFAULT_SETTINGS)   # settings 테이블의 열과 같은 순서


def new_uid():
    return uuid.uuid4().hex


def valid_uid(uid):
    return bool(uid) and UID_RE.fullmatch(uid) is not None


def new_id():
    return uuid.uuid4().hex[:8]


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _empty():
    return {"settings": dict(DEFAULT_SETTINGS), "completed": [], "current": [], "onboarded": False, "settings_done": False}


# ------------------------------------------------------------------
# 불러오기 / 저장
# ------------------------------------------------------------------

def load(uid):
    if not valid_uid(uid):
        raise ValueError("올바르지 않은 사용자 번호")
    with _lock:
        conn = _connect()
        try:
            return _load(conn, uid)
        finally:
            conn.close()


def _load(conn, uid):
    user = conn.execute("SELECT onboarded, settings_done FROM users WHERE uid = ?", (uid,)).fetchone()
    if user is None:
        return _empty()
    data = _empty()
    data["onboarded"] = bool(user["onboarded"])
    data["settings_done"] = bool(user["settings_done"])
    row = conn.execute("SELECT * FROM settings WHERE uid = ?", (uid,)).fetchone()
    if row is not None:
        for key in SETTING_KEYS:
            data["settings"][key] = row[key]
    data["completed"] = [
        {"id": r["id"], "semester": r["semester"], "name": r["name"], "credit": r["credit"],
         "type": r["type"], "required": bool(r["required"]), "grade": r["grade"]}
        for r in conn.execute("SELECT * FROM completed_courses WHERE uid = ? ORDER BY seq", (uid,))]
    data["current"] = [
        {"id": r["id"], "name": r["name"], "credit": r["credit"], "type": r["type"],
         "required": bool(r["required"]), "score": r["score"], "mean": r["mean"],
         "std": r["std"], "grading": r["grading"], **_extras(r)}
        for r in conn.execute("SELECT * FROM current_courses WHERE uid = ? ORDER BY seq", (uid,))]
    return data


EXTRA_KEYS = ("exam_ratio", "fin_score", "fin_ratio", "max_score", "fin_max")        # 숫자 한 칸짜리 추가 값
ALTER_COLUMNS = {**{k: "REAL" for k in EXTRA_KEYS}, "att_score": "REAL", "att_ratio": "REAL",
                 "asg_score": "REAL", "asg_ratio": "REAL", "items_json": "TEXT"}
LEGACY_ITEMS = (("출석", "att_score", "att_ratio"), ("과제", "asg_score", "asg_ratio"))   # 예전 버전 열


def _extras(row):
    """중간 반영 비율·기말 반영 비율·기타 항목(퀴즈, 과제, 출석 등). 입력하지 않은 과목은 키 자체를 넣지 않음."""
    d = {k: row[k] for k in EXTRA_KEYS if row[k] is not None}
    items = json.loads(row["items_json"]) if row["items_json"] else []
    if not items:                                    # 예전 버전(출석·과제 고정 열)으로 저장한 값도 읽어 줌
        for name, sk, rk in LEGACY_ITEMS:
            if row[sk] is not None and row[rk] is not None:
                items.append({"name": name, "score": row[sk], "ratio": row[rk]})
    if items:
        d["items"] = items
    return d


def _write_user(conn, uid, data):
    """한 사용자의 데이터를 통째로 교체합니다. 호출하는 쪽의 트랜잭션 안에서 실행됩니다."""
    conn.execute("INSERT OR IGNORE INTO users (uid) VALUES (?)", (uid,))
    conn.execute("UPDATE users SET onboarded = ?, settings_done = ? WHERE uid = ?",
                 (1 if data.get("onboarded") else 0, 1 if data.get("settings_done") else 0, uid))

    s = data["settings"]
    cols = ", ".join(SETTING_KEYS)
    marks = ", ".join("?" for _ in SETTING_KEYS)
    conn.execute(f"INSERT OR REPLACE INTO settings (uid, {cols}) VALUES (?, {marks})",
                 (uid, *[s.get(k, DEFAULT_SETTINGS[k]) for k in SETTING_KEYS]))

    conn.execute("DELETE FROM completed_courses WHERE uid = ?", (uid,))
    conn.executemany(
        "INSERT INTO completed_courses (uid, id, semester, name, credit, type, required, grade) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(uid, c["id"], c["semester"], c["name"], c["credit"], c["type"],
          1 if c.get("required") else 0, c["grade"]) for c in data["completed"]])

    conn.execute("DELETE FROM current_courses WHERE uid = ?", (uid,))
    conn.executemany(
        "INSERT INTO current_courses (uid, id, name, credit, type, required, score, mean, std, grading, "
        "exam_ratio, fin_score, fin_ratio, max_score, fin_max, items_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(uid, c["id"], c["name"], c["credit"], c["type"], 1 if c.get("required") else 0,
          c["score"], c["mean"], c["std"], c["grading"], *[c.get(k) for k in EXTRA_KEYS],
          json.dumps(c["items"], ensure_ascii=False) if c.get("items") else None)
         for c in data["current"]])


def set_mode(uid, mode):
    """시점(중간고사 이후/기말고사 이후)만 바꿉니다. 사용자 데이터 전체를 다시 쓰지 않아 빠릅니다."""
    if not valid_uid(uid):
        raise ValueError("올바르지 않은 사용자 번호")
    with _lock:
        conn = _connect()
        try:
            with conn:
                cur = conn.execute("UPDATE settings SET mode = ? WHERE uid = ?", (mode, uid))
                if cur.rowcount == 0:                                   # 설정을 아직 저장한 적 없는 사용자
                    data = _load(conn, uid)
                    data["settings"]["mode"] = mode
                    _write_user(conn, uid, data)
        finally:
            conn.close()


def save(uid, data):
    if not valid_uid(uid):
        raise ValueError("올바르지 않은 사용자 번호")
    with _lock:
        conn = _connect()
        try:
            with conn:                      # 성공하면 commit, 예외가 나면 자동 rollback
                _write_user(conn, uid, data)
        finally:
            conn.close()


# ------------------------------------------------------------------
# 시작할 때: 테이블 생성 + JSON 이전
# ------------------------------------------------------------------

def _read_json_user(path):
    """예전 JSON 파일을 읽어 save()가 받는 모양으로 바꿉니다. 형식이 이상하면 예외를 냅니다."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    data = _empty()
    saved = raw.get("settings", {})
    for key in SETTING_KEYS:                # 예전 버전에서 쓰던 설정 이름은 무시
        if key in saved:
            data["settings"][key] = saved[key]
    data["completed"] = [
        {"id": str(c["id"]), "semester": c["semester"], "name": c["name"], "credit": c["credit"],
         "type": c["type"], "required": bool(c.get("required", False)), "grade": c["grade"]}
        for c in raw.get("completed", [])]
    data["current"] = [
        {"id": str(c["id"]), "name": c["name"], "credit": c["credit"], "type": c["type"],
         "required": bool(c.get("required", False)), "score": c["score"], "mean": c["mean"],
         "std": c["std"], "grading": c["grading"],
         **{k: c[k] for k in EXTRA_KEYS if c.get(k) is not None},
         **({"items": c["items"]} if c.get("items") else {})}
        for c in raw.get("current", [])]
    data["onboarded"] = bool(raw.get("onboarded", False))
    data["settings_done"] = bool(raw.get("settings_done", False))
    return data


def migrate_json():
    """data/users/*.json 을 DB로 옮깁니다. 파일 하나당 한 번만, 파일 하나당 하나의 트랜잭션으로 처리합니다.

    - 이미 옮긴 파일(migrated_files에 기록됨)은 건너뜁니다.
    - DB에 같은 uid가 이미 있으면 덮어쓰지 않고 건너뜁니다 (중복 방지).
    - 실패하면 그 파일만 rollback하고 원본 JSON은 그대로 둡니다. 원인은 화면(터미널)에 출력됩니다.
    - 성공해도 JSON 파일은 삭제하지 않습니다.
    반환값: {"migrated": [...], "skipped": [...], "failed": {파일: 오류}}
    """
    report = {"migrated": [], "skipped": [], "failed": {}}
    for path in sorted(glob.glob(os.path.join(JSON_DIR, "*.json"))):
        name = os.path.basename(path)
        uid = name[:-5]
        with _lock:
            conn = _connect()
            try:
                if conn.execute("SELECT 1 FROM migrated_files WHERE filename = ?", (name,)).fetchone():
                    report["skipped"].append(name)
                    continue
                try:
                    if not valid_uid(uid):
                        raise ValueError("파일 이름이 사용자 번호 형식(영문 소문자·숫자 32자)이 아님")
                    data = _read_json_user(path)
                    with conn:
                        if conn.execute("SELECT 1 FROM users WHERE uid = ?", (uid,)).fetchone():
                            conn.execute("INSERT INTO migrated_files (filename, result) VALUES (?, ?)",
                                         (name, "skipped: uid already in DB"))
                            report["skipped"].append(name)
                            continue
                        _write_user(conn, uid, data)
                        conn.execute("INSERT INTO migrated_files (filename, result) VALUES (?, ?)", (name, "ok"))
                    report["migrated"].append(name)
                except Exception as e:      # 이 파일만 실패 처리하고 다음 파일로 진행
                    report["failed"][name] = f"{type(e).__name__}: {e}"
                    print(f"[GradePath] JSON 이전 실패 ({name}): {type(e).__name__}: {e} "
                          f"- 원본 JSON은 그대로 있습니다.", file=sys.stderr)
            finally:
                conn.close()
    return report


def init():
    """DB 파일과 테이블이 없으면 만들고, 예전 JSON이 있으면 한 번 옮깁니다."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _lock:
        conn = _connect()
        try:
            with conn:
                conn.executescript(SCHEMA)
                # 예전 버전으로 만든 DB에는 새 설정 열이 없으므로 추가 (기존 데이터는 그대로 유지)
                ucols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
                if "settings_done" not in ucols:
                    conn.execute("ALTER TABLE users ADD COLUMN settings_done INTEGER NOT NULL DEFAULT 0")
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(settings)")}
                ccols = {r["name"] for r in conn.execute("PRAGMA table_info(current_courses)")}
                for k, typ in ALTER_COLUMNS.items():
                    if k not in ccols:
                        conn.execute(f"ALTER TABLE current_courses ADD COLUMN {k} {typ}")
                if "extra_semesters" not in cols:
                    conn.execute("ALTER TABLE settings ADD COLUMN extra_semesters INTEGER NOT NULL DEFAULT 0")
                if "max_credits_per_year" not in cols:
                    conn.execute("ALTER TABLE settings ADD COLUMN max_credits_per_year INTEGER NOT NULL DEFAULT 37")
        finally:
            conn.close()
    return migrate_json()
