"""calc.py 계산 시험.  실행:  python tests/test_calc.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calc  # noqa: E402

SETTINGS = {
    "total_credits_required": 130, "max_credits_per_semester": 21, "max_credits_per_year": 40,
    "remaining_semesters": 4, "seasonal_plan_credits": 0,
    "target_gpa": 3.5, "mode": "mid", "retake_cap": "A0", "retake_max_prior": "C+",
}


def C(i, credit, grade, name="x"):
    return {"id": i, "name": name, "credit": credit, "grade": grade}


def cur(i, score, mean, std, grading="relative", credit=3):
    return {"id": i, "name": "c" + i, "credit": credit, "score": score,
            "mean": mean, "std": std, "grading": grading}


class TestGpa(unittest.TestCase):
    def test_weighted(self):
        self.assertAlmostEqual(calc.calc_gpa([C("1", 3, "A+"), C("2", 2, "F")]), 2.7)

    def test_empty(self):
        self.assertIsNone(calc.calc_gpa([]))

    def test_earned_excludes_f(self):
        self.assertEqual(calc.earned_credits([C("1", 3, "A+"), C("2", 2, "F")]), 3)


class TestEstimate(unittest.TestCase):
    def test_mean_is_median(self):
        self.assertAlmostEqual(calc.top_percent(0), 50.0)

    def test_grade_monotonic(self):
        order = {g: i for i, g in enumerate(calc.GRADE_ORDER)}
        prev = 99
        for score in range(40, 100, 5):
            g = calc.grade_at(cur("a", score, 70, 10))
            self.assertLessEqual(order[g], prev)
            prev = order[g]

    def test_top_student_gets_a_plus(self):
        self.assertEqual(calc.grade_at(cur("a", 95, 70, 10)), "A+")

    def test_average_student_b_range(self):
        self.assertIn(calc.grade_at(cur("a", 70, 70, 10)), ("B+", "B0"))

    def test_absolute(self):
        self.assertEqual(calc.grade_at(cur("a", 91, 70, 10, "absolute")), "A0")
        self.assertEqual(calc.grade_at(cur("a", 59, 70, 10, "absolute")), "F")

    def test_relaxed_not_worse(self):
        order = {g: i for i, g in enumerate(calc.GRADE_ORDER)}
        for score in range(50, 95, 3):
            a = calc.grade_at(cur("a", score, 70, 10, "relative"))
            b = calc.grade_at(cur("a", score, 70, 10, "relative_relaxed"))
            self.assertLessEqual(order[b], order[a])

    def test_relaxed_cutoffs_increasing(self):
        cuts = calc.relative_cutoffs(True)
        vals = [cuts[g] for g in calc.GRADE_ORDER]
        self.assertEqual(vals, sorted(vals))
        self.assertEqual(len(set(vals)), len(vals))

    def test_range_order(self):
        order = {g: i for i, g in enumerate(calc.GRADE_ORDER)}
        e = calc.estimate_course(cur("a", 75, 70, 10), 0.6)
        self.assertLessEqual(order[e["best"]], order[e["expected"]])
        self.assertLessEqual(order[e["expected"]], order[e["worst"]])


class TestPredict(unittest.TestCase):
    def test_probability_extremes(self):
        done = [C("d", 60, "A+")]
        s = dict(SETTINGS, target_gpa=0.0)
        r = calc.predict_semester(done, [cur("1", 80, 70, 10)], s)
        self.assertEqual(r["probability"], 1.0)
        s = dict(SETTINGS, target_gpa=4.5)
        r = calc.predict_semester([C("d", 60, "B0")], [cur("1", 60, 70, 10)], s)
        self.assertEqual(r["probability"], 0.0)
        self.assertFalse(r["reachable"] and r["probability"] > 0)

    def test_required_avg(self):
        done = [C("d", 60, "A0")]           # 4.0
        s = dict(SETTINGS, target_gpa=3.5)
        r = calc.predict_semester(done, [cur("1", 70, 70, 10, credit=60)], s)
        self.assertAlmostEqual(r["required_avg_point"], 3.0)

    def test_scenario_order(self):
        r = calc.predict_semester([C("d", 30, "B0")], [cur("1", 75, 70, 10), cur("2", 65, 70, 10)], SETTINGS)
        sc = r["scenarios"]
        self.assertLessEqual(sc["pessimistic"]["cumulative_gpa"], sc["expected"]["cumulative_gpa"])
        self.assertLessEqual(sc["expected"]["cumulative_gpa"], sc["optimistic"]["cumulative_gpa"])


class TestBurden(unittest.TestCase):
    def test_basic(self):
        b = calc.graduation_burden(100, SETTINGS)
        self.assertEqual(b["remaining"], 30)
        self.assertAlmostEqual(b["per_semester"], 7.5)
        self.assertEqual(b["extra_semesters"], 0)
        self.assertEqual(b["label"], "여유")

    def test_delay(self):
        s = dict(SETTINGS, remaining_semesters=1)
        b = calc.graduation_burden(60, s)      # 70 left, 1 semester, max 21
        self.assertEqual(b["extra_semesters"], 3)
        self.assertEqual(b["label"], "졸업 지연 위험")

    def test_seasonal_uses_only_planned_credits(self):
        # 계획 학점만 반영하고, 계획이 없으면 자동으로 빼지 않는다
        b0 = calc.graduation_burden(100, SETTINGS)
        self.assertEqual(b0["need_regular"], 30)
        s = dict(SETTINGS, seasonal_plan_credits=6)
        b = calc.graduation_burden(100, s)
        self.assertEqual(b["need_regular"], 24)
        self.assertEqual(b["seasonal_plan"], 6)
        self.assertAlmostEqual(b["per_semester_without_seasonal"], 7.5)

    def test_seasonal_plan_capped_by_remaining(self):
        s = dict(SETTINGS, seasonal_plan_credits=50)
        b = calc.graduation_burden(120, s)      # 10 left
        self.assertEqual(b["seasonal_plan"], 10)
        self.assertEqual(b["need_regular"], 0)

    def test_no_semesters_left(self):
        s = dict(SETTINGS, remaining_semesters=0)
        b = calc.graduation_burden(100, s)
        self.assertIsNone(b["per_semester"])
        self.assertGreater(b["extra_semesters"], 0)

    def test_done(self):
        b = calc.graduation_burden(140, SETTINGS)
        self.assertEqual(b["remaining"], 0)
        self.assertEqual(b["label"], "여유")


class TestWithdraw(unittest.TestCase):
    def test_withdraw_bad_course_raises_gpa(self):
        done = [C("d", 60, "A0")]
        current = [cur("1", 90, 60, 10), cur("2", 30, 70, 10)]   # 2번은 F 예상
        r = calc.analyze_withdraw(done, current, "2", SETTINGS)
        self.assertGreaterEqual(r["expected"]["withdraw"]["gpa"], r["expected"]["stay"]["gpa"])

    def test_withdraw_loses_credits(self):
        done = [C("d", 60, "A0")]
        current = [cur("1", 90, 60, 10), cur("2", 80, 70, 10)]
        r = calc.analyze_withdraw(done, current, "2", SETTINGS)
        self.assertEqual(r["expected"]["stay"]["earned"] - r["expected"]["withdraw"]["earned"], 3)


class TestRetake(unittest.TestCase):
    def test_cap_applied(self):
        done = [C("1", 3, "D0"), C("2", 3, "A+")]
        r = calc.analyze_retake(done, "1", SETTINGS)
        top = r["rows"][0]
        self.assertEqual(top["applied"], "A0")
        self.assertTrue(top["capped"])
        self.assertAlmostEqual(top["gpa"], (3 * 4.0 + 3 * 4.5) / 6)

    def test_break_even(self):
        done = [C("1", 3, "C0"), C("2", 3, "A+")]
        r = calc.analyze_retake(done, "1", SETTINGS)
        self.assertEqual(r["break_even"], "C+")      # C0(2.0)보다 높은 가장 낮은 성적

    def test_eligibility(self):
        done = [C("1", 3, "B0"), C("2", 3, "C+")]
        self.assertFalse(calc.analyze_retake(done, "1", SETTINGS)["eligible"])
        self.assertTrue(calc.analyze_retake(done, "2", SETTINGS)["eligible"])

    def test_retake_f_adds_credits(self):
        done = [C("1", 3, "F"), C("2", 3, "A+")]
        r = calc.analyze_retake(done, "1", SETTINGS)
        self.assertEqual(r["rows"][0]["earned_delta"], 3)
        self.assertEqual(r["rows"][-1]["earned_delta"], 0)      # 다시 F면 변화 없음


class TestRuleBounds(unittest.TestCase):
    def test_top_30_percent_a_plus_to_a0(self):
        self.assertEqual(calc.rule_grade_bounds(cur("a", 95, 70, 10)), ("A+", "A0"))

    def test_middle_zone_b(self):
        # 평균 바로 아래(상위 ~60%)는 30~70% 구간
        self.assertEqual(calc.rule_grade_bounds(cur("a", 68, 70, 10)), ("B+", "B0"))

    def test_bottom_zone_max_c_plus(self):
        mx, mn = calc.rule_grade_bounds(cur("a", 50, 70, 10))
        self.assertEqual(mx, "C+")
        order = {g: i for i, g in enumerate(calc.GRADE_ORDER)}
        self.assertGreaterEqual(order[mn], order["C+"])

    def test_absolute_same(self):
        self.assertEqual(calc.rule_grade_bounds(cur("a", 91, 70, 10, "absolute")), ("A0", "A0"))

    def test_max_never_below_min(self):
        order = {g: i for i, g in enumerate(calc.GRADE_ORDER)}
        for mode in ("relative", "relative_relaxed", "absolute"):
            for score in range(30, 100, 4):
                mx, mn = calc.rule_grade_bounds(cur("a", score, 70, 10, mode))
                self.assertLessEqual(order[mx], order[mn])

    def test_rule_scenarios(self):
        r = calc.predict_semester([C("d", 30, "B0")], [cur("1", 95, 70, 10)], SETTINGS)
        mx, mn = r["rule_scenarios"]["max"], r["rule_scenarios"]["min"]
        self.assertAlmostEqual(mx["semester_gpa"], 4.5)
        self.assertAlmostEqual(mn["semester_gpa"], 4.0)
        self.assertGreater(mx["cumulative_gpa"], mn["cumulative_gpa"])


class TestCreditLimits(unittest.TestCase):
    def test_year_cap_limits_semester_capacity(self):
        b = calc.graduation_burden(60, dict(SETTINGS, remaining_semesters=2))   # 70 left
        self.assertEqual(b["semester_cap"], 20)                    # min(21, 40/2)
        self.assertEqual(b["extra_semesters"], 2)                  # ceil(70/20)=4 - 2

    def test_semester_cap_when_year_large(self):
        b = calc.graduation_burden(100, dict(SETTINGS, max_credits_per_semester=18, max_credits_per_year=40))
        self.assertEqual(b["semester_cap"], 18)

    def test_extra_credit_eligible(self):
        done = [dict(C("1", 9, "A+"), semester="s1"), dict(C("2", 3, "A+"), semester="s1"),
                dict(C("3", 3, "F"), semester="s0")]
        done = [done[2]] + done[:2]                                # 마지막 학기 = s1 (평점 4.5, 12학점)
        r = calc.extra_credit_status(done, dict(SETTINGS, max_credits_per_semester=19))
        self.assertEqual((r["semester"], r["eligible"], r["extra"], r["next_max"]), ("s1", True, 3, 22))

    def test_extra_credit_needs_gpa_and_credits(self):
        low_gpa = [dict(C("1", 12, "B+"), semester="s")]
        self.assertFalse(calc.extra_credit_status(low_gpa, SETTINGS)["eligible"])
        few = [dict(C("1", 9, "A+"), semester="s")]                # 12학점 미만
        self.assertFalse(calc.extra_credit_status(few, SETTINGS)["eligible"])
        self.assertEqual(calc.extra_credit_status(few, SETTINGS)["next_max"], 21)

    def test_extra_credit_boundary_375(self):
        # 평균 3.75 경계 부근: 낮은 경우와 충분히 높은 경우
        done = [dict(C("1", 3, "A0"), semester="s"), dict(C("2", 12, "B+"), semester="s")]   # (12+42)/15=3.6
        self.assertFalse(calc.extra_credit_status(done, SETTINGS)["eligible"])
        done = [dict(C("1", 6, "A+"), semester="s"), dict(C("2", 6, "B+"), semester="s")]    # (27+21)/12=4.0
        self.assertTrue(calc.extra_credit_status(done, SETTINGS)["eligible"])
        done = [dict(C("1", 3, "A+"), semester="s"), dict(C("2", 9, "A0"), semester="s")]    # (13.5+36)/12=4.125
        self.assertTrue(calc.extra_credit_status(done, SETTINGS)["eligible"])

    def test_extra_credit_none_when_empty(self):
        self.assertIsNone(calc.extra_credit_status([], SETTINGS))


class TestSimulate(unittest.TestCase):
    def setUp(self):
        self.done = [C("d", 30, "B0")]
        self.current = [cur("1", 75, 70, 10), cur("2", 65, 70, 10)]

    def test_rows_cover_all_grades_and_monotonic(self):
        r = calc.simulate_course_grades(self.done, self.current, "1", SETTINGS)
        self.assertEqual([x["grade"] for x in r["rows"]], calc.GRADE_ORDER)
        cums = [x["cumulative_gpa"] for x in r["rows"]]
        self.assertEqual(cums, sorted(cums, reverse=True))

    def test_expected_row_matches_baseline(self):
        r = calc.simulate_course_grades(self.done, self.current, "1", SETTINGS)
        exp = [x for x in r["rows"] if x["is_expected"]]
        self.assertEqual(len(exp), 1)
        self.assertAlmostEqual(exp[0]["delta"], 0.0)
        self.assertAlmostEqual(exp[0]["cumulative_gpa"], r["base"]["cumulative_gpa"])
        self.assertEqual(exp[0]["grade"], r["expected_grade"])

    def test_value_checked_by_hand(self):
        # 과목1 A+(4.5), 과목2는 예상 학점 고정. 누적 = (30*3.0 + 3*4.5 + 3*p2) / 36
        p2 = calc.GRADE_POINTS[calc.grade_at(self.current[1])]
        r = calc.simulate_course_grades(self.done, self.current, "1", SETTINGS)
        self.assertAlmostEqual(r["rows"][0]["cumulative_gpa"], (90 + 13.5 + 3 * p2) / 36)
        self.assertAlmostEqual(r["rows"][0]["semester_gpa"], (4.5 + p2) / 2)

    def test_needed_grade_is_lowest_that_meets_target(self):
        s = dict(SETTINGS, target_gpa=3.1)
        r = calc.simulate_course_grades(self.done, self.current, "1", s)
        ok = [x["grade"] for x in r["rows"] if x["meets_target"]]
        self.assertEqual(r["needed_grade"], ok[-1])
        self.assertTrue(all(x["meets_target"] for x in r["rows"][:len(ok)]))     # 높은 등급일수록 달성

    def test_impossible_and_always(self):
        r = calc.simulate_course_grades(self.done, self.current, "1", dict(SETTINGS, target_gpa=4.5))
        self.assertIsNone(r["needed_grade"])
        r = calc.simulate_course_grades(self.done, self.current, "1", dict(SETTINGS, target_gpa=0.0))
        self.assertEqual(r["needed_grade"], "F")

    def test_pass_fail_history_not_counted(self):
        r = calc.simulate_course_grades([C("p", 3, "P"), C("n", 3, "NP")], self.current, "1", SETTINGS)
        self.assertAlmostEqual(r["rows"][0]["cumulative_gpa"], r["rows"][0]["semester_gpa"])


class TestMode(unittest.TestCase):
    def test_final_range_narrower(self):
        c = cur("a", 75, 70, 10)
        order = {g: i for i, g in enumerate(calc.GRADE_ORDER)}
        mid = calc.predict_semester([C("d", 30, "B0")], [c], dict(SETTINGS, mode="mid"))
        fin = calc.predict_semester([C("d", 30, "B0")], [c], dict(SETTINGS, mode="final"))
        self.assertGreater(mid["uncertainty"], fin["uncertainty"])
        em, ef = mid["estimates"]["a"], fin["estimates"]["a"]
        self.assertLessEqual(order[ef["worst"]] - order[ef["best"]], order[em["worst"]] - order[em["best"]])

    def test_probability_reports_trials(self):
        r = calc.predict_semester([C("d", 30, "B0")], [cur("a", 75, 70, 10)], SETTINGS)
        self.assertEqual(r["trials"], 3000)
        self.assertAlmostEqual(r["probability"], r["hits"] / r["trials"])

    def test_withdraw_semester_gpa(self):
        done = [C("d", 60, "A0")]
        current = [cur("1", 90, 60, 10), cur("2", 30, 70, 10)]
        r = calc.analyze_withdraw(done, current, "2", SETTINGS)
        self.assertGreater(r["expected"]["withdraw"]["semester_gpa"], r["expected"]["stay"]["semester_gpa"])
        self.assertNotEqual(r["expected"]["stay"]["semester_gpa"], r["expected"]["stay"]["gpa"])

    def test_withdraw_final_note(self):
        r = calc.analyze_withdraw([], [cur("1", 80, 70, 10)], "1", dict(SETTINGS, mode="final"))
        self.assertTrue(any("기간" in n for n in r["notes"]))


class TestRetakeExtra(unittest.TestCase):
    def test_semester_gpa_with_others(self):
        done = [C("1", 3, "D0")]
        r = calc.analyze_retake(done, "1", SETTINGS, other_credits=15, other_avg_point=4.0)
        top = r["rows"][0]                         # 받은 A+ -> 반영 A0(4.0)
        self.assertAlmostEqual(top["semester_gpa"], 4.0)
        low = r["rows"][-1]                        # F
        self.assertAlmostEqual(low["semester_gpa"], (0 + 15 * 4.0) / 18)

    def test_candidates(self):
        done = [{"id": "1", "name": "a", "credit": 3, "grade": "C+", "semester": "s"},
                {"id": "2", "name": "b", "credit": 3, "grade": "B0", "semester": "s"},
                {"id": "3", "name": "c", "credit": 3, "grade": "P", "semester": "s"}]
        cands = calc.retake_candidates(done, [cur("x", 40, 70, 10)], SETTINGS)
        self.assertEqual([(c["source"], c["id"]) for c in cands], [("completed", "1"), ("current", "x")])


class TestPassFail(unittest.TestCase):
    def test_gpa_excludes_pass_fail(self):
        courses = [C("1", 3, "A0"), C("2", 3, "P"), C("3", 3, "NP")]
        self.assertAlmostEqual(calc.calc_gpa(courses), 4.0)

    def test_only_pass_fail_gpa_none(self):
        self.assertIsNone(calc.calc_gpa([C("1", 3, "P")]))

    def test_earned(self):
        courses = [C("1", 3, "A0"), C("2", 2, "P"), C("3", 3, "NP"), C("4", 3, "F")]
        self.assertEqual(calc.earned_credits(courses), 5)

    def test_predict_with_pass_fail_history(self):
        done = [C("1", 3, "B0"), C("2", 2, "P")]
        r = calc.predict_semester(done, [cur("a", 80, 70, 10)], SETTINGS)
        need = (3.5 * 6 - 3 * 3.0) / 3      # P 학점은 평균 계산에서 빠짐
        self.assertAlmostEqual(r["required_avg_point"], need)

    def test_withdraw_with_pass_fail_history(self):
        done = [C("1", 3, "P")]
        r = calc.analyze_withdraw(done, [cur("a", 80, 70, 10)], "a", SETTINGS)
        self.assertIsNone(r["expected"]["withdraw"]["gpa"])


class TestEvalComponents(unittest.TestCase):
    def test_exam_only_unchanged(self):
        c = cur("a", 80, 70, 10)
        self.assertEqual(calc.eff_stats(c), (80, 70, 10))

    def test_weighted_combination(self):
        c = {**cur("a", 80, 70, 10), "exam_ratio": 40, "items": [{"name": "출석", "score": 100, "ratio": 10}]}
        s, m, sd = calc.eff_stats(c)          # 비율 40:10 -> 0.8 : 0.2
        self.assertAlmostEqual(s, 0.8 * 80 + 0.2 * 100)
        self.assertAlmostEqual(m, 0.8 * 70 + 0.2 * calc.ATTENDANCE_ASSUMED["mean"])
        self.assertAlmostEqual(sd, 0.8 * 10 + 0.2 * calc.ATTENDANCE_ASSUMED["std"])

    def test_both_extras_and_absolute(self):
        c = {**cur("a", 90, 70, 10, "absolute"), "exam_ratio": 50,
             "items": [{"name": "출석", "score": 100, "ratio": 20}, {"name": "퀴즈", "score": 80, "ratio": 30}]}
        s, _, _ = calc.eff_stats(c)
        self.assertAlmostEqual(s, 0.5 * 90 + 0.2 * 100 + 0.3 * 80)
        self.assertEqual(calc.grade_at(c), calc.grade_from_score(s))

    def test_final_needed_table(self):
        c = {**cur("a", 80, 70, 10), "exam_ratio": 40, "fin_ratio": 60}
        fn = calc.final_needed(c)
        pts = [g["min_score"] for g in fn["grades"] if g["min_score"] is not None]
        self.assertEqual(pts, sorted(pts, reverse=True))                # 높은 학점일수록 더 높은 점수가 필요
        pt = [calc.GRADE_POINTS[t["grade"]] for t in fn["table"]]
        self.assertEqual(pt, sorted(pt, reverse=True))    # 점수가 높을수록 학점이 같거나 높음
        need = {g["grade"]: g["min_score"] for g in fn["grades"]}["A0"]
        if need is not None:
            got = calc.grade_at({**c, "fin_score": need})
            self.assertGreaterEqual(calc.GRADE_POINTS[got], calc.GRADE_POINTS["A0"])
        self.assertIsNone(calc.final_needed(cur("a", 80, 70, 10)))      # 기말 비율 없으면 계산 안 함
        self.assertIn("a", calc.predict_semester([], [c], SETTINGS)["final_needed"])

    def test_low_extra_pulls_grade_down(self):
        base = cur("a", 85, 70, 10)
        low = {**base, "exam_ratio": 50, "items": [{"name": "과제", "score": 0, "ratio": 50}]}
        self.assertLessEqual(calc.GRADE_POINTS[calc.estimate_course(low, 0.6)["expected"]],
                             calc.GRADE_POINTS[calc.estimate_course(base, 0.6)["expected"]])


class TestPlanGuide(unittest.TestCase):
    PLAN = {**cur("a", 78, 70, 10), "exam_ratio": 30, "fin_ratio": 40,
            "items": [{"name": "퀴즈", "score": 80, "ratio": 10}, {"name": "출석", "score": 100, "ratio": 10}]}

    def test_current_and_scenarios(self):
        p = calc.final_needed(self.PLAN)
        cu = p["current"]
        self.assertAlmostEqual(cu["earned"], 78 * 0.3 + 8 + 10)           # 41.4
        self.assertEqual((cu["known_ratio"], cu["total_ratio"]), (50, 90))
        self.assertAlmostEqual(cu["max_possible"], cu["earned"] + 40)
        self.assertEqual([s["label"] for s in p["scenarios"]], ["최소", "낮음", "평균", "높음", "최대"])
        totals = [s["total"] for s in p["scenarios"]]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(len(p["curve"]), 21)

    def test_deterministic(self):
        self.assertEqual(calc.final_needed(self.PLAN), calc.final_needed(dict(self.PLAN)))
        a = calc.predict_semester([], [self.PLAN], SETTINGS)
        b = calc.predict_semester([], [self.PLAN], SETTINGS)
        self.assertEqual(a, b)                                            # 모의 계산도 항상 같은 값

    def test_target_threshold_matches_grade(self):
        p = calc.final_needed(self.PLAN)
        for g in p["grades"]:
            if g["min_score"] is not None:
                got = calc.grade_at({**self.PLAN, "fin_score": g["min_score"]})
                self.assertGreaterEqual(calc.GRADE_POINTS[got], calc.GRADE_POINTS[g["grade"]])

    def test_life_guide(self):
        done = [C("1", 3, "A0"), C("2", 3, "B+")]
        done[0]["type"] = "major"
        done[1]["type"] = "lib"
        g = calc.life_guide(done, [{**cur("a", 78, 70, 10), "type": "major"}], {**SETTINGS, "major_credits_required": 70})
        self.assertEqual(g["rows"][0]["kind"], "now")
        self.assertEqual(sum(r["credits"] for r in g["rows"]), 130 - 6)   # 취득 6 + 남은 것의 합 = 졸업 학점
        self.assertEqual(g["progress"]["total"]["done"], 6)
        for r in g["rows"]:
            self.assertEqual(r["major"] + r["lib"], r["credits"])


class TestGuidePlans(unittest.TestCase):
    """바쁜 학기를 고려한 학점 배분안 (균등형·균형형·최소형)."""
    def setUp(self):
        from rules import DEFAULT_SETTINGS
        self.st = {**DEFAULT_SETTINGS, "remaining_semesters": 6, "major_credits_required": 63}
        self.cur = [{"id": "1", "name": "a", "credit": 3, "type": "major"}, {"id": "2", "name": "b", "credit": 3, "type": "lib"}]
        self.done = [{"id": "x", "semester": "s", "name": "x", "credit": 34, "type": "major", "grade": "A0"}]

    def plans(self, busy=None):
        g = calc.life_guide(self.done, self.cur, self.st, busy)
        return g, {p["key"]: p for p in g["plans"]}

    def fut(self, p):
        return [r["credits"] for r in p["rows"] if r["kind"] == "future"]

    def test_totals_equal_need_in_every_plan(self):
        g, ps = self.plans()
        need = 130 - 34 - 6
        for p in ps.values():
            self.assertEqual(sum(self.fut(p)), need)
            self.assertTrue(p["feasible"])

    def test_default_busy_is_fourth_year(self):
        g, _ = self.plans()
        self.assertEqual(g["busy"], [7, 8])

    def test_balanced_and_minimal_reduce_busy_semesters(self):
        _, ps = self.plans()
        even, bal, mn = (self.fut(ps[k]) for k in ("even", "balanced", "minimal"))
        self.assertEqual(even, [15] * 6)
        self.assertEqual(bal[-2:], [9, 9])                  # 가중치 0.5
        self.assertTrue(mn[-1] <= bal[-1] and mn[-2] <= bal[-2])   # 최소형이 더 적음
        self.assertEqual(mn[-2:], [8, 8])                   # 90 - 74(한도 합)
        self.assertEqual(max(mn), 19)

    def test_caps_and_year_limit(self):
        _, ps = self.plans()
        for p in ps.values():
            fut = [r for r in p["rows"] if r["kind"] == "future"]
            self.assertTrue(all(r["credits"] <= r["cap"] for r in fut))
            # 같은 학년도 두 학기 합이 학년도 한도 이하
            for y in (2, 3, 4):
                self.assertTrue(sum(r["credits"] for r in fut if r["year"] == y) <= 37)

    def test_no_busy_means_identical_plans(self):
        _, ps = self.plans([])
        self.assertEqual(self.fut(ps["even"]), self.fut(ps["balanced"]))
        self.assertEqual(self.fut(ps["even"]), self.fut(ps["minimal"]))

    def test_infeasible_reports_shortfall(self):
        self.done[0]["credit"] = 3                          # 남은 학점이 너무 많음
        _, ps = self.plans()
        self.assertFalse(ps["even"]["feasible"])
        self.assertEqual(ps["even"]["shortfall"], ps["minimal"]["shortfall"])
        self.assertGreater(ps["even"]["shortfall"], 0)
        self.assertIn("졸업이 어렵습니다", ps["even"]["summary"])

    def test_major_split_sums(self):
        _, ps = self.plans()
        for p in ps.values():
            fut = [r for r in p["rows"] if r["kind"] == "future"]
            self.assertEqual(sum(r["major"] for r in fut), 63 - 34 - 3)     # 남은 전공 학점
            self.assertTrue(all(r["major"] + r["lib"] == r["credits"] for r in fut))

    def test_same_input_same_output(self):
        a = calc.life_guide(self.done, self.cur, self.st, [7, 8])
        b = calc.life_guide(self.done, self.cur, self.st, [7, 8])
        self.assertEqual(a, b)

    def test_allocate_respects_caps(self):
        res, left = calc._allocate([1, 1, 1], [5, 5, 5], 20)
        self.assertEqual((res, left), ([5, 5, 5], 5))
        res, left = calc._allocate([1, 0.5], [10, 10], 9)
        self.assertEqual((sum(res), left), (9, 0))
        self.assertEqual(res, [6, 3])


class TestMaxScore(unittest.TestCase):
    EX = {**cur("a", 27, 21.02, 6), "max_score": 35, "exam_ratio": 35, "fin_ratio": 40, "fin_max": 40,
          "items": [{"name": "퀴즈", "score": 7.01, "max": 10, "ratio": 10}, {"name": "과제", "score": 82, "ratio": 5}]}

    def test_normalized_example(self):
        n = calc.normalized(self.EX)
        self.assertEqual([round(n["score"], 2), round(n["mean"], 2), round(n["std"], 2)], [77.14, 60.06, 17.14])
        self.assertEqual([round(i["score"], 2) for i in n["items"]], [70.1, 82.0])

    def test_default_max_is_100(self):
        base = cur("a", 78, 70, 10)
        for mx in (None, "", 0, -5, "abc"):
            self.assertEqual(calc.eff_stats({**base, "max_score": mx}), calc.eff_stats(base))
        self.assertEqual(calc.eff_stats(base), (78, 70, 10))

    def test_same_result_as_prescaled(self):
        a = {**cur("a", 27, 21.0, 7), "max_score": 35}
        b = cur("a", 77.142857142857, 60.0, 20.0)
        for x, y in zip(calc.eff_stats(a), calc.eff_stats(b)):
            self.assertAlmostEqual(x, y, places=6)
        self.assertEqual(calc.estimate_course(a, 0.6)["expected"], calc.estimate_course(b, 0.6)["expected"])

    def test_final_table_in_final_max_units(self):
        p = calc.final_needed(self.EX)
        self.assertEqual([t["score"] for t in p["table"]], [40, 30, 20, 10, 0])
        self.assertEqual(p["final_max"], 40)
        self.assertEqual(p["scenarios"][0]["final_score"], 0)
        self.assertEqual(p["scenarios"][-1]["final_score"], 40)
        self.assertEqual(p["curve"][-1]["final_score"], 40)
        # 표시 점수 x (100/40)로 되돌려 넣으면 같은 학점이 나옴 (환산 총점·학점은 100점 기준 계산)
        for t in p["table"]:
            self.assertEqual(calc.grade_at({**self.EX, "fin_score": t["score"] * 100 / 40}), t["grade"])
        for g in p["grades"]:
            if g["min_score"] is not None:
                got = calc.grade_at({**self.EX, "fin_score": g["min_score"] * 100 / 40})
                self.assertGreaterEqual(calc.GRADE_POINTS[got], calc.GRADE_POINTS[g["grade"]])

    def test_final_100_unchanged(self):
        c = {**cur("a", 78, 70, 10), "exam_ratio": 40, "fin_ratio": 60}
        self.assertEqual(calc.final_needed(c), calc.final_needed({**c, "fin_max": 100, "max_score": 100}))


if __name__ == "__main__":
    unittest.main()
