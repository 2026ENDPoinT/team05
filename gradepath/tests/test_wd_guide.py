"""수강 철회의 전공·교양 취득 학점 구분, 취득 학점 변화 없음 사유, 학업 가이드 타임라인 시험."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calc  # noqa: E402
from rules import DEFAULT_SETTINGS  # noqa: E402

DONE = [{"id": "x", "semester": "2025년 1학기", "name": "x", "credit": 6, "type": "major", "grade": "A0"},
        {"id": "y", "semester": "2025년 1학기", "name": "y", "credit": 3, "type": "lib", "grade": "B0"},
        {"id": "z", "semester": "2025년 2학기", "name": "z", "credit": 3, "type": "major", "grade": "B+"},
        {"id": "w", "semester": "2025년 여름학기", "name": "w", "credit": 2, "type": "lib", "grade": "A0"}]


def cur(i, credit, typ, score, grading="relative"):
    return {"id": i, "name": i, "credit": credit, "type": typ, "score": score, "mean": 60, "std": 10, "grading": grading}


class TestWithdrawByType(unittest.TestCase):
    def test_major_course_lowers_only_major_credits(self):
        r = calc.analyze_withdraw(DONE, [cur("a", 3, "major", 85), cur("b", 2, "lib", 85)], "a", DEFAULT_SETTINGS)
        s, w = r["expected"]["stay"], r["expected"]["withdraw"]
        self.assertEqual((s["earned_major"] - w["earned_major"], s["earned_lib"] - w["earned_lib"]), (3, 0))
        self.assertEqual(w["earned_major"] + w["earned_lib"], w["earned"])
        self.assertEqual(r["course"]["type"], "major")
        self.assertIn("전공 3학점, 교양 0학점", " ".join(r["notes"]))

    def test_lib_course_lowers_only_lib_credits(self):
        r = calc.analyze_withdraw(DONE, [cur("a", 3, "major", 85), cur("b", 2, "lib", 85)], "b", DEFAULT_SETTINGS)
        s, w = r["expected"]["stay"], r["expected"]["withdraw"]
        self.assertEqual((s["earned_major"] - w["earned_major"], s["earned_lib"] - w["earned_lib"]), (0, 2))

    def test_unchanged_credit_reason_distinguishes_absolute_from_pf(self):
        r = calc.analyze_withdraw(DONE, [cur("a", 3, "major", 30, "absolute")], "a", DEFAULT_SETTINGS)
        self.assertEqual(r["estimate"]["expected"], "F")
        self.assertIn("P/F", r["credit_reason"])
        self.assertIn("절대평가", r["credit_reason"])
        r2 = calc.analyze_withdraw(DONE, [cur("a", 3, "major", 20)], "a", DEFAULT_SETTINGS)
        self.assertNotIn("절대평가", r2["credit_reason"] or "")

    def test_reason_is_none_when_credits_change(self):
        r = calc.analyze_withdraw(DONE, [cur("a", 3, "major", 85)], "a", DEFAULT_SETTINGS)
        self.assertIsNone(r["credit_reason"])


class TestGuideTimeline(unittest.TestCase):
    def guide(self, remaining=6):
        st = {**DEFAULT_SETTINGS, "remaining_semesters": remaining, "seasonal_plan_credits": 3}
        return calc.life_guide(DONE, [cur("a", 3, "major", 70)], st)

    def test_timeline_starts_at_first_year(self):
        g = self.guide()
        self.assertEqual([t["kind"] for t in g["timeline"]], ["past", "now"] + ["future"] * 6)
        self.assertEqual((g["timeline"][0]["year"], g["timeline"][0]["term"]), (1, 1))

    def test_past_rows_use_entered_regular_semesters_only(self):
        g = self.guide()           # 이번 학기 = 2번째 → 지난 학기는 1학년 1학기 하나
        self.assertEqual(len(g["past"]), 1)
        self.assertEqual(g["past"][0]["semester"], "2025년 2학기")      # 가장 최근 정규 학기가 직전 학기에 대응
        self.assertEqual(g["past"][0]["credits"], 3)
        g = self.guide(5)          # 이번 학기 = 3번째 → 지난 학기 2개
        self.assertEqual([p["semester"] for p in g["past"]], ["2025년 1학기", "2025년 2학기"])
        self.assertEqual([p["credits"] for p in g["past"]], [9, 3])

    def test_seasonal_entered_and_planned(self):
        g = self.guide()
        self.assertEqual(g["seasonal_entered"], [{"semester": "2025년 여름학기", "credits": 2}])
        self.assertEqual(g["seasonal_plan"], 3)

    def test_empty_semester_marked_not_entered(self):
        g = calc.life_guide([], [], {**DEFAULT_SETTINGS, "remaining_semesters": 4}, None)
        self.assertTrue(all(not p["entered"] for p in g["past"]))
        self.assertEqual(len(g["past"]), 3)


if __name__ == "__main__":
    unittest.main()
