"""importer.py + 불러오기 API 시험.  실행:  python tests/test_importer.py"""
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import importer  # noqa: E402
import storage  # noqa: E402

CSV = """학기,과목명,학점,구분,필수,성적
2025년 1학기,프로그래밍입문,3,전공,필수,A0
2025년 1학기,미분적분학,3,교양,,B+
2025년 2학기,선형대수학,3,전공,,C+
"""


def xlsx_bytes(rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestParse(unittest.TestCase):
    def test_csv_basic(self):
        rows, errors = importer.parse_file("a.csv", CSV.encode("utf-8"))
        self.assertEqual(errors, [])
        self.assertEqual([(r["name"], r["type"], r["required"], r["grade"]) for r in rows],
                         [("프로그래밍입문", "major", True, "A0"), ("미분적분학", "lib", False, "B+"),
                          ("선형대수학", "major", False, "C+")])
        self.assertEqual(rows[0]["line"], 2)

    def test_cp949_csv(self):
        rows, errors = importer.parse_file("a.csv", CSV.encode("cp949"))
        self.assertEqual(len(rows), 3)

    def test_template_examples_are_skipped(self):
        # 양식의 (예시) 줄을 그대로 올려도 가짜 과목이 들어오지 않음
        with self.assertRaises(ValueError):
            importer.parse_file("t.csv", importer.template_csv().encode("utf-8"))
        data = importer.template_csv() + "2026-1,진짜과목,3,전공,,B0\n"
        rows, errors = importer.parse_file("t.csv", data.encode("utf-8"))
        self.assertEqual((len(rows), errors), (1, []))
        self.assertEqual((rows[0]["semester"], rows[0]["name"]), ("2026년 1학기", "진짜과목"))

    def test_xlsx_template_is_valid_and_skips_examples(self):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(importer.template_xlsx()))
        ws = wb.worksheets[0]
        self.assertEqual([c.value for c in ws[2]], ["학기", "과목명", "학점", "구분", "필수", "성적"])
        self.assertTrue(str(ws["B3"].value).startswith("(예시)"))
        ws["A6"], ws["B6"], ws["C6"], ws["D6"], ws["F6"] = "26-2", "내과목", 3, "교양", "A+"
        buf = io.BytesIO()
        wb.save(buf)
        rows, errors = importer.parse_file("t.xlsx", buf.getvalue())
        self.assertEqual((len(rows), errors), (1, []))
        self.assertEqual(rows[0]["semester"], "2026년 2학기")

    def test_xlsx_numbers_and_floats(self):
        data = xlsx_bytes([["학기", "과목명", "학점", "구분", "필수", "성적"],
                           ["2025년 1학기", "물리", 3.0, "교양", None, "A+"]])
        rows, errors = importer.parse_file("a.xlsx", data)
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["credit"], 3)

    def test_alias_headers_and_school_categories(self):
        t = [["수강학기", "교과목명", "이수학점", "이수구분", "성적"],
             ["2025-1", "자료구조", "3", "전공필수", "A⁰"],
             ["2025-1", "글쓰기", "2", "교양선택", "P"],
             ["2025-1", "물리", "3", "교양필수", "NP"]]
        rows, errors = importer.parse_table(t)
        self.assertEqual(errors, [])
        self.assertEqual([(r["type"], r["required"], r["grade"]) for r in rows],
                         [("major", True, "A0"), ("lib", False, "P"), ("lib", True, "NP")])

    def test_header_not_on_first_row(self):
        t = [["내 성적표"], [], ["학기", "과목명", "학점", "성적"], ["2025", "a", 3, "B0"]]
        rows, errors = importer.parse_table(t)
        self.assertEqual((len(rows), rows[0]["line"]), (1, 4))

    def test_pf_aliases(self):
        t = [["학기", "과목명", "학점", "성적"], ["s", "a", 2, "합격"], ["s", "b", 2, "불합격"],
             ["s", "c", 2, "F(P/F)"], ["s", "d", 3, "F"]]
        rows, errors = importer.parse_table(t)
        self.assertEqual([r["grade"] for r in rows], ["P", "NP", "NP", "F"])     # 일반 F는 그대로 F

    def test_row_errors_reported_with_line(self):
        t = [["학기", "과목명", "학점", "구분", "성적"],
             ["2025", "a", 3, "전공", "A"],            # 모호한 성적
             ["2025", "b", 9, "전공", "A0"],           # 학점 범위
             ["2025", "c", 2.5, "전공", "A0"],         # 정수 아님
             ["2025", "d", 3, "기타", "A0"],           # 구분
             ["", "", 3, "전공", "Z"],                  # 여러 오류
             ["2025", "ok", 3, "전공", "A0"]]
        rows, errors = importer.parse_table(t)
        self.assertEqual([r["name"] for r in rows], ["ok"])
        self.assertEqual([e["line"] for e in errors], [2, 3, 4, 5, 6])
        self.assertIn("학기가 비어", errors[-1]["message"])

    def test_blank_rows_skipped(self):
        t = [["학기", "과목명", "학점", "성적"], [None, None, None, None], ["2025", "a", 3, "B0"]]
        rows, errors = importer.parse_table(t)
        self.assertEqual((len(rows), errors), (1, []))

    def test_bad_inputs(self):
        for name, data in (("a.xls", b"x"), ("a.pdf", b"x"), ("a.xlsx", b"not a zip"),
                           ("a.csv", "이름,나이\n철수,3\n".encode())):
            with self.assertRaises(ValueError):
                importer.parse_file(name, data)

    def test_too_many_rows(self):
        t = [["학기", "과목명", "학점", "성적"]] + [["s", f"n{i}", 3, "B0"] for i in range(importer.MAX_ROWS + 1)]
        with self.assertRaises(ValueError):
            importer.parse_table(t)


class TestApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = (storage.BASE_DIR, storage.DB_PATH, storage.JSON_DIR)
        storage.BASE_DIR = self.tmp
        storage.DB_PATH = os.path.join(self.tmp, "g.db")
        storage.JSON_DIR = os.path.join(self.tmp, "users")
        import app as A
        self.c = A.app.test_client()
        storage.init()

    def tearDown(self):
        storage.BASE_DIR, storage.DB_PATH, storage.JSON_DIR = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def upload(self, name, data):
        return self.c.post("/api/import/preview", data={"file": (io.BytesIO(data), name)},
                           content_type="multipart/form-data")

    def test_preview_then_bulk_and_dedupe(self):
        r = self.upload("a.csv", CSV.encode())
        j = r.get_json()
        self.assertEqual((r.status_code, len(j["rows"]), len(j["errors"])), (200, 3, 0))
        self.assertFalse(any(x["duplicate"] for x in j["rows"]))
        self.assertEqual(self.c.get("/api/state").get_json()["completed"], [])     # 미리 보기만으로는 저장 안 됨
        r = self.c.post("/api/completed/bulk", json={"rows": j["rows"]})
        self.assertEqual(r.get_json(), {"ok": True, "added": 3, "skipped": 0})
        self.assertEqual(len(self.c.get("/api/state").get_json()["completed"]), 3)
        # 같은 파일을 다시 올리면 모두 중복
        j2 = self.upload("a.csv", CSV.encode()).get_json()
        self.assertTrue(all(x["duplicate"] for x in j2["rows"]))
        r = self.c.post("/api/completed/bulk", json={"rows": j2["rows"]})
        self.assertEqual(r.get_json(), {"ok": True, "added": 0, "skipped": 3})
        self.assertEqual(len(self.c.get("/api/state").get_json()["completed"]), 3)

    def test_settings_done_flag(self):
        """설정을 저장하기 전에는 settings_done이 False, 저장하면 True가 되고 다른 저장에도 유지됩니다."""
        self.assertFalse(self.c.get("/api/state").get_json()["settings_done"])
        self.c.post("/api/completed", json=dict(semester="s", name="a", credit=3, type="lib", grade="A0"))
        self.assertFalse(self.c.get("/api/state").get_json()["settings_done"])      # 과목만 추가해서는 바뀌지 않음
        s = self.c.get("/api/state").get_json()["settings"]
        r = self.c.put("/api/settings", json={k: s[k] for k in (
            "total_credits_required", "major_credits_required", "max_credits_per_semester", "max_credits_per_year",
            "remaining_semesters", "seasonal_plan_credits", "target_gpa", "retake_cap", "retake_max_prior")})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.c.get("/api/state").get_json()["settings_done"])
        self.c.post("/api/completed", json=dict(semester="s", name="b", credit=3, type="lib", grade="B0"))
        self.assertTrue(self.c.get("/api/state").get_json()["settings_done"])

    def test_guide_busy_param_and_explain_fallback(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.c.post("/api/current", json=dict(name="a", credit=3, type="major", score=80, mean=70, std=10, grading="relative_relaxed"))
        g = self.c.get("/api/guide?busy=7,8").get_json()
        self.assertEqual(g["busy"], [7, 8])
        self.assertEqual({p["key"] for p in g["plans"]}, {"even", "balanced", "minimal"})
        g0 = self.c.get("/api/guide?busy=").get_json()
        self.assertEqual(g0["busy"], [])
        self.assertEqual(self.c.get("/api/guide?busy=abc").status_code, 400)
        r = self.c.post("/api/explain-guide", json={"busy": [7, 8]}).get_json()
        self.assertEqual(r["source"], "rule")
        self.assertIn("균형형", r["text"])
        self.assertEqual(r["facts"]["busy_semesters"], ["4학년 1학기", "4학년 2학기"])

    def test_bulk_is_all_or_nothing(self):
        rows = [dict(semester="s", name="a", credit=3, type="lib", grade="A0"),
                dict(semester="s", name="b", credit=3, type="lib", grade="Q9", line=7)]
        r = self.c.post("/api/completed/bulk", json={"rows": rows})
        self.assertEqual(r.status_code, 400)
        self.assertIn("7번째 줄", r.get_json()["error"])
        self.assertEqual(self.c.get("/api/state").get_json()["completed"], [])

    def test_errors_and_limits(self):
        self.assertEqual(self.c.post("/api/import/preview").status_code, 400)
        self.assertEqual(self.upload("a.xls", b"x").status_code, 400)
        self.assertEqual(self.upload("a.csv", b"x" * (1024 * 1024 + 10)).status_code, 413)
        self.assertEqual(self.c.post("/api/completed/bulk", json={"rows": []}).status_code, 400)

    def test_duplicate_inside_file(self):
        csv_text = CSV + "2025년 1학기,미분적분학,3,교양,,B+\n"
        j = self.upload("a.csv", csv_text.encode()).get_json()
        self.assertEqual([x["duplicate"] for x in j["rows"]], [False, False, False, True])

    def test_template_download(self):
        r = self.c.get("/api/completed/template.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertTrue(r.data.startswith("﻿학기".encode("utf-8")))

    def test_summary_semester_gpa_and_registered(self):
        rows = [dict(semester="1학기", name="a", credit=3, type="lib", grade="A+"),
                dict(semester="1학기", name="b", credit=3, type="lib", grade="B0"),
                dict(semester="2학기", name="c", credit=2, type="lib", grade="P"),
                dict(semester="2학기", name="d", credit=3, type="major", grade="F")]
        self.c.post("/api/completed/bulk", json={"rows": rows})
        j = self.c.get("/api/summary").get_json()
        self.assertEqual(j["registered"], 11)
        self.assertEqual(j["earned"], 8)
        s1, s2 = j["semesters"]
        self.assertAlmostEqual(s1["gpa"], 3.75)
        self.assertEqual((s1["credits"], s1["earned"]), (6, 6))
        self.assertAlmostEqual(s2["gpa"], 0.0)                 # P는 제외, F(0점) 3학점만 계산
        self.assertEqual((s2["credits"], s2["earned"]), (5, 2))
        self.assertAlmostEqual(j["gpa"], (3 * 4.5 + 3 * 3.0 + 0) / 9)

    def test_invalid_input_rejected(self):
        base = dict(semester="s", name="a", credit=3, type="lib", grade="A+")
        bad = [dict(name="  "), dict(credit=0), dict(credit=-1), dict(credit="abc"), dict(credit=3.5),
               dict(credit="3.5"), dict(credit=None), dict(credit=True), dict(grade="Z"), dict(grade="A"), dict(grade="")]
        for change in bad:
            r = self.c.post("/api/completed", json={**base, **change})
            self.assertEqual(r.status_code, 400, change)
        self.assertEqual(self.c.post("/api/completed", data="not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.c.get("/api/state").get_json()["completed"], [])        # 잘못된 입력은 하나도 저장되지 않음
        self.assertEqual(self.c.post("/api/completed", json={**base, "credit": "3"}).status_code, 200)   # 문자열 정수는 허용
        self.assertEqual(self.c.post("/api/completed", json={**base, "name": "b", "credit": 3.0}).status_code, 200)

    def test_simulate_api(self):
        self.c.post("/api/current", json=dict(name="a", credit=3, type="major", score=75, mean=70, std=10, grading="relative"))
        cid = self.c.get("/api/state").get_json()["current"][0]["id"]
        r = self.c.post("/api/simulate", json={"course_id": cid})
        j = r.get_json()
        self.assertEqual((r.status_code, len(j["rows"])), (200, 9))
        self.assertEqual(self.c.post("/api/simulate", json={"course_id": "zzz"}).status_code, 400)

    def test_current_extra_eval_api(self):
        base = dict(name="a", credit=3, type="major", score=75, mean=70, std=10, grading="relative")
        bad = [dict(items=[{"name": "출석", "score": 90, "ratio": 10}]),                      # 중간 비율 없음
               dict(exam_ratio=60, items=[{"name": "출석", "score": 90}]),                  # 비율 없음
               dict(exam_ratio=80, items=[{"name": "출석", "score": 90, "ratio": 30}]),      # 합 > 100
               dict(exam_ratio=50, items=[{"name": "출석", "score": 120, "ratio": 10}]),
               dict(exam_ratio=50, items=[{"name": "과제", "score": 90, "ratio": 0}]),
               dict(exam_ratio=50, items=[{"name": "", "score": 90, "ratio": 10}]),
               dict(exam_ratio=50, items="abc"),
               dict(exam_ratio=10, items=[{"name": "x%d" % i, "score": 1, "ratio": 1} for i in range(9)])]
        for b in bad:
            self.assertEqual(self.c.post("/api/current", json={**base, **b}).status_code, 400, b)
        self.assertEqual(self.c.get("/api/state").get_json()["current"], [])
        self.assertEqual(self.c.post("/api/current", json={**base, "fin_ratio": 40}).status_code, 400)   # 중간 비율 필요
        self.assertEqual(self.c.post("/api/current", json={**base, "exam_ratio": 60, "fin_ratio": 50}).status_code, 400)
        ok = dict(exam_ratio=30, fin_ratio=30, items=[{"name": "출석", "score": 95.0, "ratio": 10.0}, {"name": "과제", "score": 80.5, "ratio": 20.0}])
        self.assertEqual(self.c.post("/api/current", json={**base, **ok}).status_code, 200)
        self.assertEqual(self.c.post("/api/current", json={**base, "name": "b"}).status_code, 200)
        cur = self.c.get("/api/state").get_json()["current"]
        self.assertEqual({k: cur[0][k] for k in ok}, ok)
        self.assertNotIn("exam_ratio", cur[1])                    # 시험만 입력한 과목은 키 없음
        cid = cur[0]["id"]
        self.assertEqual(self.c.put("/api/current/" + cid, json=base).status_code, 200)   # 수정으로 해제 가능
        self.assertNotIn("items", self.c.get("/api/state").get_json()["current"][0])
        self.assertEqual(self.c.get("/api/predict").status_code, 200)

    def test_chart_explain_guide_api(self):
        base = dict(name="a", credit=3, type="major", score=78, mean=70, std=10, grading="relative",
                    exam_ratio=30, fin_ratio=40, items=[{"name": "과제", "score": 70, "ratio": 20}])
        self.c.post("/api/current", json=base)
        self.c.post("/api/current", json={**base, "name": "b", "fin_ratio": None, "items": [], "exam_ratio": None})
        cur = self.c.get("/api/state").get_json()["current"]
        cid = cur[0]["id"]
        d = self.c.get("/api/chart-data").get_json()
        self.assertEqual(len(d["final_plans"]), 1)                  # 기말 비율을 넣은 과목만
        self.assertEqual(len(d["radar"]["axes"]), 2)
        self.assertEqual(self.c.get("/api/chart-data").get_json(), d)   # 같은 입력이면 같은 값
        csv_text = self.c.get("/api/chart-data?format=csv").data.decode("utf-8")
        self.assertIn("기말 점수별 환산 점수", csv_text)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        r = self.c.post("/api/explain", json={"course_id": cid, "target_grade": "A0"})
        j = r.get_json()
        self.assertEqual((r.status_code, j["source"]), (200, "rule"))
        self.assertEqual(self.c.post("/api/explain", json={"course_id": cur[1]["id"], "target_grade": "A0"}).status_code, 400)
        self.assertEqual(self.c.post("/api/explain", json={"course_id": cid, "target_grade": "F"}).status_code, 400)
        g = self.c.get("/api/guide").get_json()
        self.assertIn("progress", g)

    def test_llm_failure_falls_back(self):
        import llm
        c = dict(name="a", credit=3, type="major", score=78, mean=70, std=10, grading="relative",
                 exam_ratio=30, fin_ratio=40, items=[])
        os.environ["ANTHROPIC_API_KEY"] = "x"
        try:
            ok = llm.explain(c, "A0", call=lambda facts, key: "- 문장입니다.")
            self.assertEqual((ok["source"], ok["text"]), ("ai", "- 문장입니다."))
            def boom(facts, key):
                raise RuntimeError("x")
            bad = llm.explain(c, "A0", call=boom)
            self.assertEqual(bad["source"], "rule")
            self.assertEqual(ok["facts"], bad["facts"])              # LLM이 바뀌어도 숫자(근거)는 같음
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_max_score_api(self):
        base = dict(name="a", credit=3, type="major", score=27, mean=21.02, std=6, grading="relative")
        r = self.c.post("/api/current", json={**base, "max_score": 35})
        self.assertEqual(r.status_code, 200)
        r = self.c.post("/api/current", json={**base, "score": 36, "max_score": 35})
        self.assertEqual(r.status_code, 400)
        self.assertIn("값은 35 이하여야 합니다", r.get_json()["error"] if "error" in r.get_json() else str(r.get_json()))
        for blank in (None, "", 0, -3):                                   # 만점이 비었거나 0 이하이면 100점 만점
            r = self.c.post("/api/current", json={**base, "name": "b", "max_score": blank})
            self.assertEqual(r.status_code, 200, blank)
        self.assertEqual(self.c.post("/api/current", json={**base, "name": "c", "score": 101}).status_code, 400)
        cur = self.c.get("/api/state").get_json()["current"]
        self.assertEqual(cur[0]["max_score"], 35)
        self.assertNotIn("max_score", cur[1])                              # 100이면 저장하지 않음 (예전 데이터와 같은 모양)
        full = dict(base, max_score=35, exam_ratio=35, fin_ratio=40, fin_max=40,
                    items=[{"name": "퀴즈", "score": 7.01, "max": 10, "ratio": 10}, {"name": "과제", "score": 82, "ratio": 5}])
        self.assertEqual(self.c.post("/api/current", json={**full, "name": "d"}).status_code, 200)
        bad = dict(full, items=[{"name": "퀴즈", "score": 11, "max": 10, "ratio": 10}])
        self.assertEqual(self.c.post("/api/current", json={**bad, "name": "e"}).status_code, 400)
        cur = self.c.get("/api/state").get_json()["current"][-1]
        self.assertEqual((cur["fin_max"], cur["items"][0]["max"]), (40, 10))
        self.assertNotIn("max", cur["items"][1])
        plans = self.c.get("/api/chart-data").get_json()["final_plans"]
        self.assertEqual([t["score"] for t in plans[0]["table"]], [40, 30, 20, 10, 0])

    def test_empty_summary_has_no_gpa(self):
        j = self.c.get("/api/summary").get_json()
        self.assertIsNone(j["gpa"])
        self.assertEqual(j["registered"], 0)

    def test_imported_feeds_retake_candidates(self):
        j = self.upload("a.csv", CSV.encode()).get_json()
        self.c.post("/api/completed/bulk", json={"rows": j["rows"]})
        cands = self.c.get("/api/retake/candidates").get_json()["candidates"]
        self.assertEqual([c["name"] for c in cands], ["선형대수학"])      # C+ 만 재수강 가능


if __name__ == "__main__":
    unittest.main()
