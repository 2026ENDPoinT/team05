"""storage.py(SQLite) 시험.  실행:  python tests/test_storage.py"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402

UID1 = "a" * 32
UID2 = "b" * 32

SAMPLE = {
    "settings": {"total_credits_required": 128, "major_credits_required": 66, "max_credits_per_semester": 19, "max_credits_per_year": 37,
                 "remaining_semesters": 3, "seasonal_plan_credits": 6, "target_gpa": 3.75, "mode": "final",
                 "retake_cap": "A0", "retake_max_prior": "C+"},
    "completed": [
        {"id": "c1", "semester": "2025년 1학기", "name": "미적분", "credit": 3, "type": "lib", "required": False, "grade": "C0"},
        {"id": "c2", "semester": "2025년 1학기", "name": "프로그래밍", "credit": 3, "type": "major", "required": True, "grade": "P"},
    ],
    "current": [
        {"id": "u1", "name": "자료구조", "credit": 3, "type": "major", "required": True,
         "score": 62.5, "mean": 70.25, "std": 11.37, "grading": "relative_relaxed"},
    ],
    "onboarded": True,
    "settings_done": True,
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = (storage.BASE_DIR, storage.DB_PATH, storage.JSON_DIR)
        storage.BASE_DIR = self.tmp
        storage.DB_PATH = os.path.join(self.tmp, "gradepath.db")
        storage.JSON_DIR = os.path.join(self.tmp, "users")
        os.makedirs(storage.JSON_DIR)

    def tearDown(self):
        storage.BASE_DIR, storage.DB_PATH, storage.JSON_DIR = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_json(self, uid, data, name=None):
        path = os.path.join(storage.JSON_DIR, (name or uid) + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return path


class TestDb(Base):
    def test_creates_db_and_tables(self):
        self.assertFalse(os.path.exists(storage.DB_PATH))
        storage.init()
        self.assertTrue(os.path.exists(storage.DB_PATH))
        names = {r[0] for r in sqlite3.connect(storage.DB_PATH).execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("users", "settings", "completed_courses", "current_courses", "migrated_files"):
            self.assertIn(t, names)

    def test_init_twice_ok(self):
        storage.init()
        storage.init()

    def test_new_user_gets_defaults(self):
        storage.init()
        d = storage.load(UID1)
        self.assertEqual(d["completed"], [])
        self.assertEqual(d["settings"]["mode"], "mid")
        self.assertFalse(d["onboarded"])

    def test_roundtrip_and_persistence(self):
        storage.init()
        storage.save(UID1, SAMPLE)
        storage.init()                                   # 서버 재시작과 같은 효과
        self.assertEqual(storage.load(UID1), SAMPLE)

    def test_update_and_delete(self):
        storage.init()
        storage.save(UID1, SAMPLE)
        d = storage.load(UID1)
        d["completed"][0]["grade"] = "B0"
        d["completed"] = [c for c in d["completed"] if c["id"] != "c2"]
        storage.save(UID1, d)
        d2 = storage.load(UID1)
        self.assertEqual([(c["id"], c["grade"]) for c in d2["completed"]], [("c1", "B0")])

    def test_order_kept(self):
        storage.init()
        d = storage.load(UID1)
        d["completed"] = [dict(SAMPLE["completed"][0], id=f"x{i}") for i in range(5)]
        storage.save(UID1, d)
        self.assertEqual([c["id"] for c in storage.load(UID1)["completed"]], [f"x{i}" for i in range(5)])

    def test_users_isolated(self):
        storage.init()
        storage.save(UID1, SAMPLE)
        self.assertEqual(storage.load(UID2)["completed"], [])

    def test_rollback_on_error(self):
        storage.init()
        storage.save(UID1, SAMPLE)
        bad = json.loads(json.dumps(SAMPLE))
        bad["completed"][0]["credit"] = 99               # CHECK 제약 위반 -> 저장 중 오류
        bad["completed"][1]["name"] = "바뀌면 안 됨"
        with self.assertRaises(sqlite3.IntegrityError):
            storage.save(UID1, bad)
        self.assertEqual(storage.load(UID1), SAMPLE)     # 이전 데이터가 그대로 남아야 함

    def test_sql_injection_text_is_stored_as_text(self):
        storage.init()
        d = json.loads(json.dumps(SAMPLE))
        d["completed"][0]["name"] = "x'); DROP TABLE users;--"
        storage.save(UID1, d)
        self.assertEqual(storage.load(UID1)["completed"][0]["name"], "x'); DROP TABLE users;--")

    def test_bad_uid(self):
        storage.init()
        with self.assertRaises(ValueError):
            storage.load("../../etc/passwd")


class TestSchemaUpgrade(Base):
    def test_old_db_without_year_column_is_upgraded(self):
        """예전에 만든 DB(학년도 최대 열 없음)를 열면 열이 추가되고 기존 데이터는 그대로여야 함"""
        storage.init()
        storage.save(UID1, SAMPLE)
        con = sqlite3.connect(storage.DB_PATH)
        con.execute("PRAGMA foreign_keys=OFF")
        con.executescript("""
            CREATE TABLE settings_old AS SELECT uid, total_credits_required, major_credits_required, max_credits_per_semester,
              remaining_semesters, seasonal_plan_credits, target_gpa, mode, retake_cap, retake_max_prior FROM settings;
            DROP TABLE settings;
            CREATE TABLE settings (uid TEXT PRIMARY KEY, total_credits_required INTEGER NOT NULL, major_credits_required INTEGER NOT NULL,
              max_credits_per_semester INTEGER NOT NULL, remaining_semesters INTEGER NOT NULL, seasonal_plan_credits INTEGER NOT NULL,
              target_gpa REAL NOT NULL, mode TEXT NOT NULL, retake_cap TEXT NOT NULL, retake_max_prior TEXT NOT NULL);
            INSERT INTO settings SELECT * FROM settings_old;
            DROP TABLE settings_old;
        """)
        con.commit()
        con.close()
        storage.init()
        d = storage.load(UID1)
        self.assertEqual(d["settings"]["max_credits_per_year"], 37)          # 기본값으로 채워짐
        self.assertEqual(d["settings"]["total_credits_required"], 128)       # 기존 값 유지
        self.assertEqual(len(d["completed"]), 2)
        storage.save(UID1, d)                                                # 다시 저장도 정상
        self.assertEqual(storage.load(UID1), d)


class TestEvalColumns(Base):
    def test_old_current_table_gets_new_columns_and_roundtrips(self):
        storage.init()
        storage.save(UID1, SAMPLE)
        con = sqlite3.connect(storage.DB_PATH)
        for k in storage.ALTER_COLUMNS:
            con.execute(f"ALTER TABLE current_courses DROP COLUMN {k}")
        con.commit()
        con.close()
        storage.init()                                   # 열이 다시 추가되어야 함
        d = storage.load(UID1)
        self.assertEqual(len(d["current"]), len(SAMPLE["current"]))
        d["current"][0].update(exam_ratio=60.0, fin_ratio=20.0, items=[{"name": "퀴즈", "score": 90.0, "ratio": 20.0}])
        storage.save(UID1, d)
        again = storage.load(UID1)
        self.assertEqual(again, d)
        self.assertEqual(again["current"][0]["items"][0]["name"], "퀴즈")


class TestLegacyItems(Base):
    def test_old_att_asg_columns_become_items(self):
        storage.init()
        storage.save(UID1, SAMPLE)
        con = sqlite3.connect(storage.DB_PATH)
        con.execute("UPDATE current_courses SET exam_ratio = 60, att_score = 90, att_ratio = 10, asg_score = 70, asg_ratio = 30, items_json = NULL")
        con.commit()
        con.close()
        items = storage.load(UID1)["current"][0]["items"]
        self.assertEqual([(i["name"], i["score"], i["ratio"]) for i in items], [("출석", 90, 10), ("과제", 70, 30)])


class TestMigration(Base):
    def test_migrates_without_loss(self):
        path = self.write_json(UID1, SAMPLE)
        before = open(path, "rb").read()
        report = storage.init()
        self.assertEqual(report["migrated"], [UID1 + ".json"])
        self.assertEqual(storage.load(UID1), SAMPLE)
        self.assertTrue(os.path.exists(path))             # JSON은 지우지 않음
        self.assertEqual(open(path, "rb").read(), before)

    def test_not_migrated_twice(self):
        self.write_json(UID1, SAMPLE)
        storage.init()
        d = storage.load(UID1)
        d["completed"].append(dict(SAMPLE["completed"][0], id="new"))   # DB에서 데이터 변경
        storage.save(UID1, d)
        report = storage.init()                           # 다시 시작
        self.assertEqual(report["migrated"], [])
        self.assertEqual(len(storage.load(UID1)["completed"]), 3)       # 덮어쓰이거나 중복되지 않음
        con = sqlite3.connect(storage.DB_PATH)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM completed_courses WHERE uid=?", (UID1,)).fetchone()[0], 3)

    def test_existing_db_user_not_overwritten(self):
        storage.init()
        storage.save(UID1, dict(SAMPLE, completed=[]))
        self.write_json(UID1, SAMPLE)
        report = storage.init()
        self.assertEqual(report["skipped"], [UID1 + ".json"])
        self.assertEqual(storage.load(UID1)["completed"], [])

    def test_failure_keeps_json_and_db_clean(self):
        broken = os.path.join(storage.JSON_DIR, UID1 + ".json")
        with open(broken, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.write_json(UID2, SAMPLE)
        report = storage.init()
        self.assertIn(UID1 + ".json", report["failed"])
        self.assertEqual(report["migrated"], [UID2 + ".json"])    # 다른 파일은 계속 진행
        self.assertTrue(os.path.exists(broken))
        self.assertEqual(storage.load(UID1)["completed"], [])
        con = sqlite3.connect(storage.DB_PATH)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM users WHERE uid=?", (UID1,)).fetchone()[0], 0)

    def test_partial_failure_rolls_back(self):
        bad = json.loads(json.dumps(SAMPLE))
        bad["current"][0]["std"] = None                   # NOT NULL 위반: completed는 이미 넣은 뒤라 rollback 확인용
        self.write_json(UID1, bad)
        report = storage.init()
        self.assertIn(UID1 + ".json", report["failed"])
        con = sqlite3.connect(storage.DB_PATH)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM completed_courses WHERE uid=?", (UID1,)).fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM users WHERE uid=?", (UID1,)).fetchone()[0], 0)

    def test_old_setting_names_ignored(self):
        old = json.loads(json.dumps(SAMPLE))
        old["settings"].update({"stage": "mid", "seasonal_count": 2, "seasonal_max_credits": 6})
        self.write_json(UID1, old)
        self.assertEqual(storage.init()["failed"], {})
        self.assertEqual(storage.load(UID1)["settings"], SAMPLE["settings"])


if __name__ == "__main__":
    unittest.main()
