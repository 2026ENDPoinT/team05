"""그래프용 데이터를 한곳에서 만듭니다. 화면 그래프와 내려받기(JSON/CSV)가 같은 데이터를 씁니다.

계산은 모두 calc.py가 하고 이 파일은 모양만 바꿉니다 (같은 입력이면 항상 같은 값).
"""
import csv
import io

import calc


def chart_data(data):
    done, current = data["completed"], data["current"]
    plans, radar_axes, radar_mine, radar_avg = [], [], [], []
    for c in current:
        s, m, _ = calc.eff_stats(c)
        radar_axes.append(c["name"])
        radar_mine.append(round(s, 2))
        radar_avg.append(round(m, 2))
        fn = calc.final_needed(c)
        if fn:
            plans.append({"course_id": c["id"], "course": c["name"], **fn})
    semesters = {}
    for c in done:
        semesters.setdefault(c["semester"], []).append(c)
    trend = [{"semester": name, "gpa": calc.calc_gpa(cs)} for name, cs in semesters.items()]
    trend = [t for t in trend if t["gpa"] is not None]
    return {
        "final_plans": plans,
        "radar": {"axes": radar_axes, "mine": radar_mine, "class_mean": radar_avg},
        "gpa_trend": trend,
    }


def chart_csv(data):
    """한 장의 CSV로 펼친 형태: 구분,이름,x,y1,y2 …  (엑셀에서 바로 그래프를 그릴 수 있게)"""
    d = chart_data(data)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["구분", "이름", "x", "내 환산 점수", "반 평균 환산 점수", "예상 학점"])
    for p in d["final_plans"]:
        for pt in p["curve"]:
            w.writerow(["기말 점수별 환산 점수", p["course"], pt["final_score"], pt["total"], pt["class_mean"], pt["grade"]])
    for i, name in enumerate(d["radar"]["axes"]):
        w.writerow(["과목별 현재 환산 점수", name, "", d["radar"]["mine"][i], d["radar"]["class_mean"][i], ""])
    for t in d["gpa_trend"]:
        w.writerow(["학기별 평균 학점", t["semester"], "", t["gpa"], "", ""])
    return "﻿" + buf.getvalue()
