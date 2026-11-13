"""GradePath 계산 알고리즘 (이 프로젝트의 핵심 파일)

웹 화면이나 Flask와 무관하게, 숫자만 넣으면 결과가 나오는 순수한 함수들입니다.
그래서 따로 시험(tests/test_calc.py)하기 쉽습니다.
"""
import math
import random

from rules import (
    GRADE_POINTS, GRADE_ORDER, RELATIVE_CUM_TOP_PERCENT, RELAX_A_EXTRA,
    ABSOLUTE_CUTOFFS, UNCERTAINTY, SIM_TRIALS, EXTRA_CREDIT_RULE,
    ATTENDANCE_ASSUMED, ASSIGNMENT_ASSUMED,
)
from semester import latest_regular, parse_semester, semester_key

EPS = 1e-9


# ------------------------------------------------------------------
# 1. 기본 통계 / 학점 계산
# ------------------------------------------------------------------

def normal_cdf(z):
    """표준정규분포에서 z 이하일 확률 (0~1). 시험 점수가 종 모양으로 퍼져 있다고 가정."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def graded(courses):
    """평점이 있는 과목만 고릅니다 (P/F 과목은 평균 학점에서 제외)."""
    return [c for c in courses if c["grade"] in GRADE_POINTS]


def calc_gpa(courses):
    """평점평균 = (학점 x 평점)의 합 / 학점의 합. P/F 과목은 제외. 계산할 과목이 없으면 None."""
    total_point = 0.0
    total_credit = 0
    for c in graded(courses):
        total_point += c["credit"] * GRADE_POINTS[c["grade"]]
        total_credit += c["credit"]
    if total_credit == 0:
        return None
    return total_point / total_credit


def earned_credits(courses):
    """취득 학점 = F, P/F 과목 불합격이 아닌 과목의 학점 합 (P는 학점 취득, 평균 학점에는 미반영)."""
    return sum(c["credit"] for c in courses if c["grade"] not in ("F", "NP"))


# ------------------------------------------------------------------
# 2. 성적 추정 (점수, 평균, 표준편차 -> 예상 학점)
# ------------------------------------------------------------------

def relative_cutoffs(relaxed=False):
    """상대평가 누적 비율표. relaxed=True면 A 계열 비율을 늘려서 돌려줍니다."""
    cuts = dict(RELATIVE_CUM_TOP_PERCENT)
    if relaxed:
        cuts["A+"] += RELAX_A_EXTRA / 2
        cuts["A0"] += RELAX_A_EXTRA
        prev = cuts["A0"]
        for g in GRADE_ORDER[2:-1]:       # B+ ~ D0
            if cuts[g] <= prev:
                cuts[g] = min(prev + 1, 99.5)
            prev = cuts[g]
    return cuts


def grade_from_top_percent(top_pct, cuts):
    for g in GRADE_ORDER:
        if top_pct <= cuts[g]:
            return g
    return "F"


def grade_from_score(score):
    for g, cutoff in ABSOLUTE_CUTOFFS:
        if score >= cutoff:
            return g
    return "F"


def z_score(score, mean, std):
    """내 점수가 평균보다 표준편차 몇 개만큼 위(+)/아래(-)인지."""
    return (score - mean) / std


def top_percent(z):
    """z점수 -> 상위 몇 % 인지 (작을수록 상위)."""
    return (1 - normal_cdf(z)) * 100


def item_stats(name):
    """항목(출석·과제·퀴즈 등)의 반 평균·표준편차 가정값. 실제 값을 모르므로 이름으로 대략 구분합니다."""
    base = ATTENDANCE_ASSUMED if "출석" in name else ASSIGNMENT_ASSUMED
    return base["mean"], base["std"]


def _max(v):
    """만점 값. 비어 있거나 0 이하이면 100으로 봅니다 (만점을 입력하지 않은 예전 데이터는 그대로 100점 만점)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 100.0
    return v if v > 0 else 100.0


def to100(value, max_score):
    """입력 점수를 100점 만점 기준으로 환산: 점수 x (100 / 만점)."""
    return value * 100.0 / _max(max_score)


def normalized(course):
    """과목의 점수·평균·표준편차·항목 점수를 모두 100점 만점으로 환산한 값. 계산은 전부 이 값으로 합니다.

    예: 중간 만점 35, 점수 27, 평균 21.02, 표준편차 6 -> 77.14 / 60.06 / 17.14
    """
    m = course.get("max_score")
    return {
        "score": to100(course["score"], m),
        "mean": to100(course["mean"], m),
        "std": to100(course["std"], m),
        "items": [{"name": it["name"], "ratio": it["ratio"], "score": to100(it["score"], it.get("max")),
                   "max": _max(it.get("max"))} for it in course.get("items") or []],
    }


def _parts(course):
    """(반영 비율, 100점 환산 점수, 반 평균, 반 표준편차) 목록: 중간고사 + 기말(점수를 알 때) + 기타 항목."""
    n = normalized(course)
    parts = [(course["exam_ratio"] if course.get("exam_ratio") else 1.0, n["score"], n["mean"], n["std"])]
    if course.get("fin_score") is not None:      # 기말고사 점수(100점 환산 값). 반 평균·표준편차는 중간고사와 같다고 가정
        parts.append((course["fin_ratio"], course["fin_score"], n["mean"], n["std"]))
    for it in n["items"]:
        m, sd = item_stats(it["name"])
        parts.append((it["ratio"], it["score"], m, sd))
    return parts


def eff_stats(course):
    """예측에 쓸 (점수, 평균, 표준편차). 모두 100점 만점으로 환산한 값입니다.

    기본은 중간고사 점수 그대로(100점 환산)입니다. 퀴즈·과제·출석 등 항목을 함께 넣으면 반영 비율(%)로 가중 평균을 내어 하나의 점수로 합칩니다.
    - 비율 합이 100%가 아니면 입력한 항목끼리만 비율을 다시 맞춥니다 (예: 중간 30, 출석 10 -> 75% : 25%).
    - 기말고사의 반 평균·표준편차는 중간고사와 같다고 가정하고, 그 밖의 항목은 rules.py의 가정값을 씁니다.
    - 합친 표준편차는 각 표준편차의 가중 평균으로 잡습니다 (항목들이 같이 움직인다고 보는 보수적 가정).
    같은 입력이면 항상 같은 값이 나옵니다 (무작위 요소 없음).
    """
    parts = _parts(course)
    if len(parts) == 1:
        return parts[0][1], parts[0][2], parts[0][3]
    total = sum(p[0] for p in parts)
    return (sum(r / total * sc for r, sc, _, _ in parts),
            sum(r / total * m for r, _, m, _ in parts),
            sum(r / total * sd for r, _, _, sd in parts))


def _nice_step(top):
    """표에 쓸 점수 간격: 5칸 이하로 나뉘는 가장 작은 '깔끔한' 간격 (만점 40 -> 10, 100 -> 20)."""
    for st in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500):
        if top / st <= 5:
            return st
    return top


def final_needed(course):
    """기말고사 반영 비율을 입력한 과목의 기말 계획: 시나리오, 목표 학점까지 필요한 기말 점수(역산), 그래프용 곡선.

    - 기말고사 반 평균·표준편차는 중간고사와 같다고 가정합니다 (100점 환산 기준으로 같은 값).
    - 지금까지 입력한 점수는 그대로 두고, 기말 점수만 0~만점으로 바꿔 봅니다.
    - 계산은 내부에서 100점 기준으로 하고, 기말 점수를 보여 주는 값(final_score, min_score 등)은
      표시용 점수 = 100점 기준 점수 x (기말 만점 / 100)로 바꿔 '기말 만점 단위'로 돌려줍니다.
    - grades   : 각 학점을 받으려면 필요한 기말 최소 점수(기말 만점 단위, 만점으로도 안 되면 None)와 그때의 환산 총점
    - scenarios: 기말 점수가 최소/낮음(평균-1표준편차)/평균/높음(평균+1표준편차)/최대일 때의 환산 총점과 학점
    - current  : 지금까지 얻은 점수(반영 비율 곱한 값), 지금까지의 환산 점수(100점 만점), 남은 비율
    - curve    : 기말 점수(만점 단위)별 내 환산 총점·반 평균 환산 점수 (그래프용)
    """
    if not course.get("fin_ratio") or course.get("fin_score") is not None:
        return None
    fmax = _max(course.get("fin_max"))
    k = fmax / 100.0                                 # 100점 기준 -> 기말 만점 단위
    shown = lambda f100: round(f100 * k, 2)

    def at(f100):
        c = {**course, "fin_score": float(f100)}
        s, m, sd = eff_stats(c)
        return s, m, sd, grade_at(c, 0.0)

    known = _parts(course)
    known_ratio = sum(p[0] for p in known)
    earned = sum(r * sc / 100 for r, sc, _, _ in known)
    total_ratio = known_ratio + course["fin_ratio"]

    scan = [(f / 2, at(f / 2)) for f in range(0, 201)]            # 100점 기준 0.0, 0.5, ... 100.0
    grades = []
    for g in GRADE_ORDER:
        if g == "F":
            continue
        ok = [(f, v) for f, v in scan if GRADE_POINTS[v[3]] >= GRADE_POINTS[g] - EPS]
        grades.append({"grade": g,
                       "min_score": shown(ok[0][0]) if ok else None,
                       "min_total": round(ok[0][1][0], 2) if ok else None})

    n = normalized(course)
    mean, std = n["mean"], n["std"]
    pts = [("최소", 0.0), ("낮음", max(0.0, mean - std)), ("평균", min(100.0, max(0.0, mean))),
           ("높음", min(100.0, mean + std)), ("최대", 100.0)]
    scenarios = []
    for label, f in pts:
        s, _, _, g = at(f)
        scenarios.append({"label": label, "final_score": shown(f), "total": round(s, 2), "grade": g})

    curve = []
    for i in range(0, 21):                           # 만점을 20칸으로 나눈 점
        f = i * 5.0
        s, m, _, g = at(f)
        curve.append({"final_score": shown(f), "total": round(s, 2), "class_mean": round(m, 2), "grade": g})

    step = _nice_step(fmax)
    disp = sorted({round(v, 2) for v in [i * step for i in range(int(fmax // step) + 1)] + [fmax]}, reverse=True)
    table = [{"score": d, "grade": at(d / k)[3]} for d in disp]
    return {
        "grades": grades, "table": table, "scenarios": scenarios, "curve": curve,
        "final_max": fmax, "final_mean": shown(mean), "final_std": round(std * k, 2),
        "current": {"earned": round(earned, 2), "known_ratio": round(known_ratio, 2),
                    "converted": round(earned / known_ratio * 100, 2) if known_ratio else None,
                    "final_ratio": course["fin_ratio"], "total_ratio": round(total_ratio, 2),
                    "max_possible": round(earned + course["fin_ratio"], 2)},
    }


def grade_at(course, shift=0.0):
    """과목의 성적을 shift(표준편차 단위)만큼 움직여 본 학점.

    shift=0   : 지금 점수 그대로
    shift>0   : 앞으로 더 잘 본 경우
    shift<0   : 앞으로 더 못 본 경우
    """
    mode = course["grading"]
    score, mean, std = eff_stats(course)
    if mode == "absolute":
        return grade_from_score(score + shift * std)
    z = z_score(score, mean, std) + shift
    cuts = relative_cutoffs(relaxed=(mode == "relative_relaxed"))
    return grade_from_top_percent(top_percent(z), cuts)


def rule_grade_bounds(course):
    """현재 점수 위치에서 학칙 비율만으로 받을 수 있는 최대/최소 학점.

    학칙은 'A0 이상 30% 이하, B0 이상 70% 이하'만 정하고, 그 안에서 A+/A0, B+/B0 비율은 교수님 재량입니다.
    - 상위 30% 이내:  최대 A+, 최소 A0
    - 30% ~ 70%:      최대 B+, 최소 B0
    - 70% 초과:       최대 C+, 최소는 예시 비율표(C 이하 세부 비율)로 계산
    구간 상한까지 등급이 채워진다고 가정한 값입니다 (교수님이 A를 적게 주면 최소보다 낮아질 수 있음).
    절대평가는 점수로 정해지므로 최대=최소입니다. (A 비율 완화 선택 시 A 구간 상한이 넓어집니다.)
    """
    score, mean, std = eff_stats(course)
    if course["grading"] == "absolute":
        g = grade_from_score(score)
        return g, g
    cuts = relative_cutoffs(relaxed=(course["grading"] == "relative_relaxed"))
    p = top_percent(z_score(score, mean, std))
    if p <= cuts["A0"]:
        return "A+", "A0"
    if p <= cuts["B0"]:
        return "B+", "B0"
    return "C+", grade_from_top_percent(p, cuts)


def estimate_course(course, uncertainty):
    """한 과목의 예상 학점 구간 (최저 ~ 최고, 중간값)과 학칙 기준 최대/최소 학점."""
    z = z_score(*eff_stats(course))
    max_grade, min_grade = rule_grade_bounds(course)
    return {
        "max_grade": max_grade,
        "min_grade": min_grade,
        "z": z,
        "top_percent": top_percent(z),
        "expected": grade_at(course, 0.0),
        "best": grade_at(course, +uncertainty),
        "worst": grade_at(course, -uncertainty),
    }


# ------------------------------------------------------------------
# 3. 목표 평균 학점 시나리오 분석
# ------------------------------------------------------------------

def simulate_gpa(done, current, uncertainty, trials=SIM_TRIALS, seed=42):
    """앞으로의 점수 변동을 3000번 무작위로 뽑아 누적 평균 학점 분포를 구합니다 (몬테카를로)."""
    rng = random.Random(seed)
    results = []
    for _ in range(trials):
        sim = []
        for c in current:
            shift = rng.gauss(0, uncertainty)
            sim.append({"credit": c["credit"], "grade": grade_at(c, shift)})
        results.append(calc_gpa(done + sim))
    results.sort()
    return results


def probability_label(p):
    if p >= 0.8:
        return "높음"
    if p >= 0.4:
        return "보통"
    if p > 0:
        return "낮음"
    return "거의 불가능"


def predict_semester(done, current, settings):
    """이번 학기 예상 성적과 목표 평균 학점 달성 가능성."""
    u = UNCERTAINTY[settings["mode"]]
    target = settings["target_gpa"]
    estimates = {c["id"]: estimate_course(c, u) for c in current}

    def scenario(which):
        cur = [{"credit": c["credit"], "grade": estimates[c["id"]][which]} for c in current]
        return {
            "semester_gpa": calc_gpa(cur),
            "cumulative_gpa": calc_gpa(done + cur),
        }

    result = {
        "estimates": estimates,
        "rule_scenarios": {k: scenario(w) for k, w in (("max", "max_grade"), ("min", "min_grade"))},
        "scenarios": {k: scenario(w) for k, w in
                      (("pessimistic", "worst"), ("expected", "expected"), ("optimistic", "best"))},
        "target_gpa": target,
        "mode": settings["mode"],
        "uncertainty": u,
        "base_gpa": calc_gpa(done),
        "final_needed": {c["id"]: final_needed(c) for c in current if final_needed(c)},
    }

    # 목표를 이루려면 이번 학기 평균 평점이 얼마여야 하는가
    done_graded = graded(done)
    done_credit = sum(c["credit"] for c in done_graded)
    done_point = sum(c["credit"] * GRADE_POINTS[c["grade"]] for c in done_graded)
    cur_credit = sum(c["credit"] for c in current)
    if cur_credit > 0:
        need = (target * (done_credit + cur_credit) - done_point) / cur_credit
        result["required_avg_point"] = need
        result["reachable"] = need <= 4.5 + EPS
        result["already_secured"] = need <= EPS
        sims = simulate_gpa(done, current, u)
        hits = sum(1 for g in sims if g >= target - EPS)
        p = hits / len(sims)
        result["probability"] = p
        result["hits"] = hits
        result["trials"] = len(sims)
        result["probability_label"] = probability_label(p)
        n = len(sims)
        result["gpa_p10"] = sims[int(n * 0.10)]
        result["gpa_p50"] = sims[int(n * 0.50)]
        result["gpa_p90"] = sims[int(n * 0.90)]
    return result


def simulate_course_grades(done, current, course_id, settings):
    """목표 GPA 시뮬레이션: 한 과목이 각 등급일 때 평균 학점이 어떻게 바뀌는지 표로 돌려줍니다.

    다른 과목은 현재 점수 기준 예상 학점으로 고정하고, 고른 과목만 A+ ~ F로 바꿔 계산합니다.
    목표 누적 평균 학점을 이루는 데 필요한 이 과목의 최소 학점도 함께 알려 줍니다.
    """
    course = next(c for c in current if c["id"] == course_id)
    target = settings["target_gpa"]
    expected = {c["id"]: grade_at(c, 0.0) for c in current}

    def gpas(grade):
        cur = [{"credit": c["credit"], "grade": grade if c["id"] == course_id else expected[c["id"]]}
               for c in current]
        return calc_gpa(cur), calc_gpa(done + cur)

    base_sem, base_cum = gpas(expected[course_id])
    rows = []
    for g in GRADE_ORDER:
        sem, cum = gpas(g)
        rows.append({
            "grade": g,
            "semester_gpa": sem,
            "cumulative_gpa": cum,
            "delta": None if cum is None or base_cum is None else cum - base_cum,
            "meets_target": cum is not None and cum >= target - EPS,
            "is_expected": g == expected[course_id],
        })
    needed = None                       # 목표를 이루는 가장 낮은 등급 (등급이 높을수록 달성하기 쉬움)
    for r in rows:
        if r["meets_target"]:
            needed = r["grade"]
    return {
        "course": {"name": course["name"], "credit": course["credit"]},
        "expected_grade": expected[course_id],
        "base": {"semester_gpa": base_sem, "cumulative_gpa": base_cum},
        "target_gpa": target,
        "needed_grade": needed,
        "rows": rows,
    }


# ------------------------------------------------------------------
# 4. 졸업 부담 계산
# ------------------------------------------------------------------

def extra_credit_status(done, settings):
    """직전 학기(입력한 마지막 학기) 성적으로 다음 학기 추가신청(+4학점) 가능 여부를 계산합니다.

    학칙: 직전 학기 평균 학점 3.75 이상이고 15학점 이상 취득했을 때, 그 학기에만 추가 신청 가능.
    입력한 학기 중 가장 최근 정규 학기(1·2학기)를 직전 학기로 봅니다. 학기 이름을 알아볼 수 없으면 마지막으로 입력한 학기. 성적이 없으면 None.
    """
    if not done:
        return None
    last = latest_regular([c["semester"] for c in done])
    sem = [c for c in done if c["semester"] == last]
    gpa = calc_gpa(sem)
    earned = earned_credits(sem)
    rule = EXTRA_CREDIT_RULE
    ok = gpa is not None and gpa >= rule["min_prev_gpa"] - EPS and earned >= rule["min_prev_earned"]
    return {
        "semester": last, "gpa": gpa, "earned": earned, "eligible": ok,
        "extra": rule["extra"] if ok else 0,
        "next_max": settings["max_credits_per_semester"] + (rule["extra"] if ok else 0),
        "min_gpa": rule["min_prev_gpa"], "min_earned": rule["min_prev_earned"],
    }


def graduation_burden(earned_total, settings):
    """졸업까지 남은 학점과, 남은 학기마다 필요한 학점."""
    remaining = max(0, settings["total_credits_required"] - earned_total)
    sem_left = settings["remaining_semesters"]
    # 계절학기는 사용자가 입력한 계획 학점만 반영합니다 (최대 가능 학점을 자동으로 빼지 않음)
    seasonal_plan = max(0, settings["seasonal_plan_credits"])
    seasonal_used = min(seasonal_plan, remaining)
    need_regular = remaining - seasonal_used
    # 학기당 최대 신청 학점과 학년도 최대(보통 2학기)로 나눈 값 중 작은 쪽이 꾸준히 채울 수 있는 학기당 학점
    max_per_sem = min(settings["max_credits_per_semester"], settings.get("max_credits_per_year", 37) / 2)

    # 계절학기를 쓰지 않았을 때의 학기당 필요 학점 (비교용)
    if remaining == 0:
        per_sem_no_seasonal = 0.0
    elif sem_left > 0:
        per_sem_no_seasonal = remaining / sem_left
    else:
        per_sem_no_seasonal = None

    if need_regular == 0:
        per_sem = 0.0
    elif sem_left > 0:
        per_sem = need_regular / sem_left
    else:
        per_sem = float("inf")

    extra_sem = max(0, math.ceil(need_regular / max_per_sem) - sem_left) if need_regular else 0

    if extra_sem > 0:
        label = "졸업 지연 위험"
    elif per_sem > max_per_sem * 0.9:
        label = "빡빡함"
    elif per_sem > max_per_sem * 0.7:
        label = "보통"
    else:
        label = "여유"

    return {
        "remaining": remaining,
        "semester_cap": max_per_sem,
        "seasonal_plan": seasonal_used,
        "per_semester_without_seasonal": per_sem_no_seasonal,
        "need_regular": need_regular,
        "per_semester": None if per_sem == float("inf") else per_sem,
        "extra_semesters": extra_sem,
        "label": label,
    }


# ------------------------------------------------------------------
# 5. 수강 철회 분석
# ------------------------------------------------------------------

def analyze_withdraw(done, current, course_id, settings):
    """철회하는 경우와 유지하는 경우를 비교합니다."""
    u = UNCERTAINTY[settings["mode"]]
    target_course = next(c for c in current if c["id"] == course_id)
    est = {c["id"]: estimate_course(c, u) for c in current}

    def build(exclude, which):
        cur = [{"credit": c["credit"], "grade": est[c["id"]][which], "type": c.get("type")}
               for c in current if c["id"] != exclude]
        allc = done + cur
        gpa = calc_gpa(allc)
        earned = earned_credits(allc)
        em = earned_credits([c for c in allc if c.get("type") == "major"])
        return {
            "gpa": gpa,                      # 전체 누적 평균 학점
            "semester_gpa": calc_gpa(cur),   # 이번 학기만의 평균 학점
            "earned": earned,
            "earned_major": em,              # 전공 취득 학점
            "earned_lib": earned - em,       # 교양 취득 학점 (전공이 아닌 모든 과목)
            "major_remaining": max(0, settings.get("major_credits_required", 0) - em),
            "burden": graduation_burden(earned, settings),
        }

    out = {
        "course": {"name": target_course["name"], "credit": target_course["credit"],
                   "type": target_course.get("type", "lib"), "grading": target_course.get("grading", "relative"),
                   "required": target_course.get("required", False)},
        "estimate": est[course_id],
        "expected": {"stay": build(None, "expected"), "withdraw": build(course_id, "expected")},
        "worst": {"stay": build(None, "worst"), "withdraw": build(course_id, "worst")},
    }

    stay, wd = out["expected"]["stay"], out["expected"]["withdraw"]
    notes = []
    if stay["gpa"] is not None and wd["gpa"] is not None:
        diff = wd["gpa"] - stay["gpa"]
        if diff > 0.005:
            notes.append(f"철회하면 예상 누적 평균 학점이 {diff:.2f} 올라갑니다.")
        elif diff < -0.005:
            notes.append(f"유지하면 예상 누적 평균 학점이 {-diff:.2f} 더 높습니다.")
        else:
            notes.append("평균 학점 차이는 거의 없습니다.")
    elif wd["gpa"] is None:
        notes.append("철회하면 이번 학기 반영 과목이 없어 평균 학점은 기존 성적만으로 계산됩니다.")
    lost = stay["earned"] - wd["earned"]
    lost_major = stay["earned_major"] - wd["earned_major"]
    lost_lib = stay["earned_lib"] - wd["earned_lib"]
    out["credit_reason"] = None
    if lost > 0:
        notes.append(f"철회하면 예상 취득 학점이 전공 {lost_major}학점, 교양 {lost_lib}학점(합계 {lost}학점) 줄어, 졸업까지 남는 학점이 그만큼 늘어납니다.")
    elif lost == 0:
        # 취득 학점이 그대로인 이유를 풀어서 알려 줌 (예상 성적이 F라서). 절대평가는 P/F와 다르다는 점도 함께.
        e = est[course_id]
        best_txt = "" if e["best"] == "F" else f" 기말에서 점수가 올라 {e['best']}까지 받게 되면 철회 시 {target_course['credit']}학점을 못 얻는 셈이 됩니다."
        if target_course.get("grading") == "absolute":
            why = ("절대평가는 P/F(합격/불합격)와 달리 점수로 A~F 학점이 정해지고, 학점은 D0(60점) 이상일 때 취득합니다. "
                   "지금 점수로는 F가 예상돼 유지해도 얻는 학점이 없어서, 철회해도 취득 학점은 그대로입니다." + best_txt)
        else:
            why = ("지금 점수 위치로는 F가 예상돼 유지해도 얻는 학점이 없어서, 철회해도 취득 학점은 그대로입니다." + best_txt)
        out["credit_reason"] = why
        notes.append(why)
    if wd["burden"]["extra_semesters"] > stay["burden"]["extra_semesters"]:
        notes.append("철회하면 졸업이 늦어질 위험이 커집니다.")
    elif wd["burden"]["label"] != stay["burden"]["label"]:
        notes.append(f"남은 학기 수강 부담이 '{stay['burden']['label']}'에서 '{wd['burden']['label']}'(으)로 바뀝니다.")
    if target_course.get("required"):
        notes.append("필수 과목이라 철회하면 이후 학기에 다시 수강해야 졸업 요건을 채울 수 있습니다.")
    if settings["mode"] == "final":
        notes.append("기말고사 이후에는 철회 신청 기간이 이미 지났을 수 있으니 학사일정을 확인하세요.")
    out["notes"] = notes
    return out


# ------------------------------------------------------------------
# 6. 재수강 분석
# ------------------------------------------------------------------

def analyze_retake(done, course_id, settings, other_credits=0, other_avg_point=0.0):
    """현재 성적 유지와 재수강 시 받을 수 있는 성적별 결과를 비교합니다.

    가정: 재수강하면 예전 성적이 새 성적으로 바뀌고, 새 성적은 상한(retake_cap)을 넘지 못합니다.
    other_credits / other_avg_point: 재수강 학기에 함께 들을 다른 과목의 학점 합과 예상 평균 평점
    (학기 평균 학점 계산용, 입력하지 않으면 이 과목만으로 계산).
    """
    target = next(c for c in done if c["id"] == course_id)
    others = [c for c in done if c["id"] != course_id]
    cap_grade = settings["retake_cap"]
    cap_point = GRADE_POINTS[cap_grade]
    base_gpa = calc_gpa(done)
    base_earned = earned_credits(done)

    rows = []
    for g in GRADE_ORDER:
        applied = g if GRADE_POINTS[g] <= cap_point else cap_grade
        new_list = others + [{"credit": target["credit"], "grade": applied}]
        gpa = calc_gpa(new_list)
        sem_credit = target["credit"] + other_credits
        sem_gpa = (target["credit"] * GRADE_POINTS[applied] + other_credits * other_avg_point) / sem_credit
        rows.append({
            "semester_gpa": sem_gpa,
            "received": g,
            "applied": applied,
            "capped": applied != g,
            "gpa": gpa,
            "delta": gpa - base_gpa,
            "earned_delta": earned_credits(new_list) - base_earned,
        })

    # 평균 학점이 오르기 시작하는 가장 낮은 성적
    break_even = None
    for r in reversed(rows):
        if r["delta"] > EPS:
            break_even = r["received"]
            break

    eligible = GRADE_POINTS[target["grade"]] <= GRADE_POINTS[settings["retake_max_prior"]]
    after_best = rows[0]
    burden_ratio = target["credit"] / settings["max_credits_per_semester"]
    return {
        "course": {"name": target["name"], "credit": target["credit"], "grade": target["grade"],
                   "required": target.get("required", False)},
        "eligible": eligible,
        "retake_max_prior": settings["retake_max_prior"],
        "base_gpa": base_gpa,
        "other_credits": other_credits,
        "rows": rows,
        "break_even": break_even,
        "max_gain": after_best["delta"],
        "burden_ratio": burden_ratio,
        "burden_credit": target["credit"],
    }


# ------------------------------------------------------------------
# 7. 재수강 후보 목록 (지난 학기 성적 + 이번 학기 예상 성적)
# ------------------------------------------------------------------

def is_retakable(grade, settings):
    """기존 성적이 재수강 가능 성적(예: C+) 이하인지. P/F 과목은 제외."""
    return grade in GRADE_POINTS and GRADE_POINTS[grade] <= GRADE_POINTS[settings["retake_max_prior"]]


def retake_candidates(done, current, settings):
    """재수강 분석을 바로 할 수 있는 과목 목록 (지난 학기 성적 + 이번 학기 예상 성적)."""
    out = []
    for c in done:
        if is_retakable(c["grade"], settings):
            out.append({"source": "completed", "id": c["id"], "name": c["name"], "credit": c["credit"],
                        "grade": c["grade"], "where": c["semester"], "required": c.get("required", False)})
    for c in current:
        g = grade_at(c, 0.0)
        if is_retakable(g, settings):
            out.append({"source": "current", "id": c["id"], "name": c["name"], "credit": c["credit"],
                        "grade": g, "where": "이번 학기 (예상)", "required": c.get("required", False)})
    return out


# ------------------------------------------------------------------
# 대학생활 가이드: 학기별 권장 이수 학점 · 전공/교양 배분 · 졸업 진행률
# ------------------------------------------------------------------

def _split_even(total, n):
    """total을 n칸에 최대한 고르게 나눕니다 (앞쪽 칸에 1씩 더 얹음)."""
    base, rem = divmod(int(total), n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def _allocate(weights, caps, total):
    """total(정수)을 weights 비율로 나누되 각 칸이 caps를 넘지 않게 합니다 (같은 입력이면 같은 결과).

    한도에 걸린 칸은 한도로 고정하고, 남은 양을 나머지 칸에 다시 비율대로 나눕니다.
    반환: (칸별 값 리스트, 한도 때문에 못 넣은 양)
    """
    n = len(weights)
    res = [0] * n
    fixed = [False] * n
    left = int(total)
    while left > 0:
        free = [i for i in range(n) if not fixed[i]]
        if not free:
            break
        wsum = sum(weights[i] for i in free)
        if wsum <= 0:
            break
        share = {i: left * weights[i] / wsum for i in free}
        over = [i for i in free if share[i] > caps[i] + 1e-9]
        if over:
            for i in over:
                res[i] = caps[i]
                fixed[i] = True
                left -= caps[i]
            continue
        base = {i: int(share[i]) for i in free}
        rem = left - sum(base.values())
        order = sorted(free, key=lambda i: (-(share[i] - base[i]), i))
        for i in order:
            res[i] = base[i]
        for i in order:                                  # 남은 학점은 소수 부분이 큰 칸부터 1씩
            if rem <= 0:
                break
            if res[i] < caps[i]:
                res[i] += 1
                rem -= 1
        left = rem                                       # 한도 때문에 못 넣은 양
        break
    return res, max(0, left)


def guide_plans(cur_cr, cur_major, idx, sem_left, need_regular, remaining_major, settings, busy=None, has_now=True):
    """남은 학점을 '바쁜 학기'를 고려해 나누는 세 가지 배분안 (모두 코드가 계산).

    - even    균등형: 모든 정규 학기에 고르게
    - balanced 균형형: 바쁜 학기는 다른 학기의 절반 비중(가중치 0.5)으로
    - minimal  최소형: 바쁜 학기를 졸업에 꼭 필요한 최소 학점으로 (나머지 학기는 한도에 가깝게)
    한도: 학기당 최대 학점, 학년도 최대 학점(두 학기 합). 이번 학기 학점이 있으면 같은 학년도의 남은 학기 한도에서 뺍니다.
    busy: 바쁜 학기의 학기 번호(1학년 1학기=1) 목록. None이면 4학년 학기(7·8번) 중 남은 학기.
    """
    if sem_left <= 0:
        return {"plans": [], "busy": [], "future": []}
    max_sem = settings["max_credits_per_semester"]
    year_max = settings.get("max_credits_per_year", 37)
    cap_a = min(max_sem, -(-year_max // 2))              # 한 학년도 첫 학기 한도 (올림)
    cap_b = min(max_sem, year_max - cap_a)               # 둘째 학기 한도
    future = []
    for i in range(sem_left):
        k = idx + 1 + i
        term = 1 if k % 2 == 1 else 2
        cap = cap_a if term == 1 else cap_b
        if term == 2 and has_now and k - 1 == idx:       # 이번 학기와 같은 학년도
            cap = max(0, min(max_sem, year_max - cur_cr))
        future.append({"idx": k, "year": (k + 1) // 2, "term": term, "cap": cap})
    nums = [f["idx"] for f in future]
    if busy is None:
        busy = [k for k in nums if (k + 1) // 2 == 4]
    busy = [k for k in nums if k in set(busy)]
    is_busy = [f["idx"] in busy for f in future]
    caps = [f["cap"] for f in future]
    total = int(need_regular)

    def split(weights):
        return _allocate(weights, caps, total)

    def minimal():
        nb = [i for i in range(len(future)) if not is_busy[i]]
        bz = [i for i in range(len(future)) if is_busy[i]]
        if not bz or not nb:
            return split([1] * len(future))
        cap_nb = sum(caps[i] for i in nb)
        need_b = max(0, total - cap_nb)
        res = [0] * len(future)
        rb, short_b = _allocate([1] * len(bz), [caps[i] for i in bz], need_b)
        rn, short_n = _allocate([1] * len(nb), [caps[i] for i in nb], total - sum(rb))
        for j, i in enumerate(bz):
            res[i] = rb[j]
        for j, i in enumerate(nb):
            res[i] = rn[j]
        return res, max(0, total - sum(res))

    def lab(f):
        return f"{f['year']}학년 {f['term']}학기"

    plans = []
    specs = [("even", "균등형", lambda: split([1] * len(future))),
             ("balanced", "균형형", lambda: split([0.5 if b else 1 for b in is_busy])),
             ("minimal", "최소형", minimal)]
    for key, name, fn in specs:
        totals, short = fn()
        majors, _ = _allocate(totals, totals, min(remaining_major, sum(totals))) if sum(totals) else ([0] * len(totals), 0)
        rows = []
        if has_now:
            now_k = idx
            rows.append({"year": (now_k + 1) // 2, "term": 1 if now_k % 2 == 1 else 2, "kind": "now",
                         "credits": cur_cr, "major": cur_major, "lib": cur_cr - cur_major, "busy": False, "over_cap": False})
        for f, t, m, b in zip(future, totals, majors, is_busy):
            rows.append({"year": f["year"], "term": f["term"], "kind": "future", "credits": t, "major": min(m, t),
                         "lib": t - min(m, t), "busy": b, "over_cap": False, "cap": f["cap"]})
        busy_c = [t for t, b in zip(totals, is_busy) if b]
        other_c = [t for t, b in zip(totals, is_busy) if not b]
        peak = max(totals) if totals else 0
        plans.append({
            "key": key, "name": name, "rows": rows, "feasible": short == 0, "shortfall": short,
            "busy_credits": busy_c, "other_avg": round(sum(other_c) / len(other_c), 1) if other_c else None,
            "peak": peak, "peak_ratio": round(peak / max_sem, 2) if max_sem else 0,
        })
    for p in plans:                                     # 설명 문장은 숫자만으로 만든 기본 문장 (LLM 아님)
        p["summary"] = _plan_summary(p, [lab(f) for f, b in zip(future, is_busy) if b], max_sem)
    return {"plans": plans, "busy": busy, "future": [{"idx": f["idx"], "year": f["year"], "term": f["term"]} for f in future],
            "default_plan": "balanced" if busy and len(busy) < len(future) else "even"}


def _plan_summary(p, busy_labels, max_sem):
    if not p["feasible"]:
        return f"이 배분으로는 정규 학기만으로 {p['shortfall']}학점이 모자라 졸업이 어렵습니다. 계절학기나 학기 수를 확인해 보세요."
    pct = round(p["peak_ratio"] * 100)
    if not p["busy_credits"] or p["other_avg"] is None:
        return f"모든 학기를 학기당 최대 {p['peak']}학점 안에서 고르게 듣습니다 (학기당 최대의 {pct}%)."
    b = sorted(set(p["busy_credits"]))
    btxt = f"{b[0]}" if len(b) == 1 else f"{b[0]}~{b[-1]}"
    return (f"바쁜 학기({', '.join(busy_labels)})는 학기당 {btxt}학점, 나머지 학기는 평균 {p['other_avg']:g}학점입니다. "
            f"가장 많이 듣는 학기는 {p['peak']}학점으로 학기당 최대({max_sem})의 {pct}%입니다.")


def _past_and_seasonal(done, idx):
    """입력한 지난 성적으로 1학년 1학기부터 이번 학기 전까지의 학기별 취득 학점을 만듭니다.

    입력한 정규 학기(1·2학기)를 시간순으로 놓고, 가장 최근 학기를 '이번 학기 바로 전'에 맞춥니다.
    여름·겨울 학기는 계절학기로 따로 모읍니다. 입력이 없는 학기는 entered=False.
    """
    regs, seas = {}, {}
    for c in done:
        p = parse_semester(c.get("semester"))
        if p is None:
            continue
        (regs if isinstance(p[1], int) else seas).setdefault(c["semester"], []).append(c)
    names = sorted(regs, key=semester_key)
    past = []
    for k in range(1, idx):
        j = len(names) - (idx - k)
        cs = regs[names[j]] if 0 <= j < len(names) else []
        e = earned_credits(cs)
        m = earned_credits([c for c in cs if c.get("type") == "major"])
        past.append({"idx": k, "year": (k + 1) // 2, "term": 1 if k % 2 == 1 else 2, "kind": "past",
                     "semester": names[j] if cs else None, "entered": bool(cs),
                     "credits": e, "major": m, "lib": e - m})
    seasonal = [{"semester": n, "credits": earned_credits(seas[n])} for n in sorted(seas, key=semester_key)]
    return past, seasonal


def life_guide(done, current, settings, busy=None):
    """이번 학기 이후 학기별 권장 이수 학점과 졸업까지의 진행 상황 (같은 입력이면 항상 같은 값).

    - 이번 학기 과목은 모두 취득한다고 보고 남은 학점을 계산합니다.
    - 계절학기는 설정에 입력한 계획 학점만큼 정규 학기에서 덜어 줍니다.
    - 학기 번호는 '8 - 남은 정규 학기 수'를 이번 학기로 보고 계산합니다 (1학년 1학기=1).
    - 권장 전공 학점은 남은 전공 학점을 남은 학기에 고르게 나눈 값입니다 (과목 개설·선후수 관계는 반영하지 않음).
    """
    total_req = settings["total_credits_required"]
    major_req = settings["major_credits_required"]
    earned = earned_credits(done)
    major_done = earned_credits([c for c in done if c["type"] == "major"])
    cur_cr = sum(c["credit"] for c in current)
    cur_major = sum(c["credit"] for c in current if c["type"] == "major")
    sem_left = settings["remaining_semesters"]
    cap = min(settings["max_credits_per_semester"], settings.get("max_credits_per_year", 37) / 2)

    idx = max(1, 8 - sem_left)                    # 이번 학기 번호
    remaining_total = max(0, total_req - earned - cur_cr)
    seasonal = min(max(0, settings["seasonal_plan_credits"]), remaining_total)
    need_regular = remaining_total - seasonal
    remaining_major = min(max(0, major_req - major_done - cur_major), need_regular)

    def label(k):
        return {"year": (k + 1) // 2, "term": 1 if k % 2 == 1 else 2}

    rows = []
    if current:
        rows.append({**label(idx), "kind": "now", "credits": cur_cr, "major": cur_major,
                     "lib": cur_cr - cur_major, "over_cap": cur_cr > cap})
    if sem_left > 0:
        totals = _split_even(need_regular, sem_left)
        majors = _split_even(remaining_major, sem_left)
        for i in range(sem_left):
            m = min(majors[i], totals[i])
            rows.append({**label(idx + 1 + i), "kind": "future", "credits": totals[i], "major": m,
                         "lib": totals[i] - m, "over_cap": totals[i] > cap})
    burden = graduation_burden(earned + cur_cr, settings)
    plan_info = guide_plans(cur_cr, cur_major, idx, sem_left, need_regular, remaining_major, settings, busy, bool(current))
    past, seasonal_entered = _past_and_seasonal(done, idx)
    timeline = [{"idx": k, "year": (k + 1) // 2, "term": 1 if k % 2 == 1 else 2,
                 "kind": "past" if k < idx else ("now" if k == idx else "future")}
                for k in range(1, idx + sem_left + 1)]

    def pct(a, b):
        return min(100.0, round(a / b * 100, 1)) if b else 100.0

    return {
        "rows": rows, "cap": cap, "seasonal_plan": seasonal, "burden_label": burden["label"],
        "past": past, "timeline": timeline, "seasonal_entered": seasonal_entered,
        "seasonal_setting": max(0, settings["seasonal_plan_credits"]),
        "extra_semesters": burden["extra_semesters"],
        **plan_info,
        "progress": {
            "total": {"done": earned, "now": cur_cr, "required": total_req,
                      "pct_done": pct(earned, total_req), "pct_with_now": pct(earned + cur_cr, total_req)},
            "major": {"done": major_done, "now": cur_major, "required": major_req,
                      "pct_done": pct(major_done, major_req), "pct_with_now": pct(major_done + cur_major, major_req)},
        },
    }
