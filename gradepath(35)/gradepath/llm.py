"""계산 결과를 읽기 쉬운 문장(취약점 분석·보완 안내)으로 바꾸는 부분.

[역할 분리]
- 숫자(환산 점수, 필요한 기말 점수, 시나리오)는 calc.py가 계산합니다. 같은 입력이면 항상 같은 값입니다.
- 이 파일은 계산이 끝난 숫자를 '문장으로 풀어 쓰는 일'만 합니다. LLM은 숫자를 새로 계산하지 않습니다.
- 환경변수 ANTHROPIC_API_KEY가 있으면 LLM(Claude)이 문장을 만들고, 없거나 실패하면 규칙 기반 문장을 보여 줍니다.
- LLM에는 과목명과 점수 숫자만 보냅니다 (이름·학번 등 개인정보는 보내지 않음).
"""
import json
import os
import urllib.request

import calc
from rules import GRADE_POINTS

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("GRADEPATH_MODEL", "claude-sonnet-5-5")
TIMEOUT = 25

SYSTEM = (
    "당신은 대학생의 학습을 돕는 코치입니다. 사용자가 준 JSON 숫자만 근거로 쓰고, 새 숫자를 계산하거나 지어내지 마세요. "
    "한국어 합니다체로, 어려운 용어는 쉬운 말로 풀어 쓰세요. 형식은 '취약점' 2~3줄, '보완 방법' 3줄입니다. "
    "각 줄은 '- '로 시작하고 한 문장으로 쓰세요. 성적을 보장하는 표현은 쓰지 마세요."
)


def build_facts(course, target_grade):
    """LLM에게 줄 사실(전부 코드가 계산한 값)."""
    plan = calc.final_needed(course)
    if plan is None:
        raise ValueError("기말고사 반영 비율을 입력한 과목만 분석할 수 있습니다.")
    n = calc.normalized(course)                       # 모든 점수는 100점 만점으로 환산한 값
    comps = [{"name": "중간고사", "score": round(n["score"], 2), "ratio": course.get("exam_ratio") or 100,
              "class_mean": round(n["mean"], 2)}]
    for it in n["items"]:
        m, _ = calc.item_stats(it["name"])
        comps.append({"name": it["name"], "score": round(it["score"], 2), "ratio": it["ratio"], "class_mean_assumed": m})
    for c in comps:
        c["points_lost"] = round((100 - c["score"]) * c["ratio"] / 100, 2)    # 이 항목에서 잃은 총점
    need = {g["grade"]: g["min_score"] for g in plan["grades"]}.get(target_grade)
    return {
        "course": course["name"],
        "target_grade": target_grade,
        "needed_final_score": need,                       # 기말 만점 단위 점수. None이면 만점으로도 어려움
        "final_max": plan["final_max"],
        "final_ratio": course["fin_ratio"],
        "final_class_mean_assumed": plan["final_mean"],      # 기말 만점 단위
        "current_converted_score": plan["current"]["converted"],
        "max_possible_total": plan["current"]["max_possible"],
        "scenarios": plan["scenarios"],
        "components": comps,
        "weakest_component": max(comps, key=lambda c: c["points_lost"])["name"],
    }


def rule_text(f):
    """LLM 없이 만드는 기본 문장 (항상 같은 입력이면 같은 문장)."""
    lines = []
    weak = max(f["components"], key=lambda c: c["points_lost"])
    lines.append(f"- 가장 많이 점수를 잃은 항목은 {weak['name']}입니다 (반영 비율 {weak['ratio']:g}%에서 총점 {weak['points_lost']:g}점 손실).")
    for c in f["components"]:
        mean = c.get("class_mean") or c.get("class_mean_assumed")
        if mean is not None and c["score"] < mean:
            lines.append(f"- {c['name']} 점수가 평균(가정 포함)보다 낮습니다 (100점 환산: {c['score']:g}점 대 {mean:g}점).")
    need = f["needed_final_score"]
    if need is None:
        lines.append(f"- {f['target_grade']}를 받으려면 기말고사 만점({f['final_max']:g}점)으로도 부족해서, 목표 학점을 낮춰 보는 것이 좋습니다.")
    elif need <= 0:
        lines.append(f"- {f['target_grade']}는 기말고사를 0점 받아도 가능한 상태입니다 (평균 가정 기준).")
    else:
        gap = need - f["final_class_mean_assumed"]
        rel = "평균보다 높은 점수가 필요합니다" if gap > 0 else "평균 정도면 가능합니다"
        lines.append(f"- {f['target_grade']}를 받으려면 기말고사 {need:g}점(만점 {f['final_max']:g}점) 이상이 필요하며, {rel}.")
    lines.append(f"- 기말고사 반영 비율이 {f['final_ratio']:g}%이므로, 남은 기간에는 기말고사 준비에 시간을 가장 많이 쓰는 것이 좋습니다.")
    lines.append(f"- {weak['name']}에서 틀린 부분을 먼저 정리하고, 남은 항목이 있다면 제출 기한을 놓치지 않도록 일정을 잡으세요.")
    return "\n".join(lines)


def _call_llm(facts, key):
    return _call_llm_with(SYSTEM, facts, key)


def _call_llm_with(system, facts, key):
    body = json.dumps({
        "model": MODEL, "max_tokens": 600, "system": system,
        "messages": [{"role": "user", "content": "다음 계산 결과를 바탕으로 작성해 주세요.\n" + json.dumps(facts, ensure_ascii=False)}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        out = json.loads(r.read().decode("utf-8"))
    text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text").strip()
    if not text:
        raise ValueError("빈 응답")
    return text


def explain(course, target_grade, call=_call_llm):
    """{'source': 'ai' | 'rule', 'text': 문장, 'facts': 근거 숫자, 'note': 안내}"""
    if target_grade not in GRADE_POINTS or target_grade == "F":
        raise ValueError("목표 학점이 올바르지 않습니다.")
    facts = build_facts(course, target_grade)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return {"source": "rule", "text": rule_text(facts), "facts": facts,
                "note": "AI 키(ANTHROPIC_API_KEY)가 설정되지 않아 기본 안내 문장을 보여 줍니다."}
    try:
        return {"source": "ai", "text": call(facts, key), "facts": facts, "note": ""}
    except Exception as e:                                 # 네트워크·키 오류 등: 앱은 계속 동작해야 함
        return {"source": "rule", "text": rule_text(facts), "facts": facts,
                "note": f"AI 응답을 받지 못해 기본 안내 문장을 보여 줍니다 ({type(e).__name__})."}


# ------------------------------------------------------------------
# 학업 가이드: 학기별 학점 배분안 설명 (숫자는 calc.life_guide가 계산, 여기서는 문장만)
# ------------------------------------------------------------------

GUIDE_SYSTEM = (
    "당신은 대학생의 수강 계획을 돕는 코치입니다. 사용자가 준 JSON 숫자만 근거로 쓰고, 새 숫자를 계산하거나 지어내지 마세요. "
    "과목 이름이나 개설 여부는 모르므로 과목을 추천하지 마세요. 한국어 합니다체로, 어려운 용어는 쉬운 말로 풀어 쓰세요. "
    "형식은 배분안(균등형·균형형·최소형)별 장단점 한 줄씩과, 마지막에 '추천' 한 줄입니다. 각 줄은 '- '로 시작하고 한 문장으로 쓰세요."
)


def build_guide_facts(guide, settings):
    """LLM에게 줄 사실(전부 코드가 계산한 값)."""
    busy = [f"{f['year']}학년 {f['term']}학기" for f in guide["future"] if f["idx"] in guide["busy"]]
    plans = [{"name": p["name"], "feasible": p["feasible"], "shortfall": p["shortfall"],
              "busy_semester_credits": p["busy_credits"], "other_semester_avg": p["other_avg"],
              "peak_credits": p["peak"], "peak_ratio_of_max": p["peak_ratio"]} for p in guide["plans"]]
    return {"max_credits_per_semester": settings["max_credits_per_semester"],
            "busy_semesters": busy, "seasonal_plan_credits": guide["seasonal_plan"], "plans": plans,
            "recommended": guide["default_plan"]}


def guide_rule_text(f):
    """LLM 없이 만드는 기본 문장."""
    by = {p["name"]: p for p in f["plans"]}
    lines = []
    if not f["busy_semesters"]:
        return "- 바쁜 학기를 고르지 않아 모든 학기를 고르게 나눈 배분만 보여 줍니다. 바쁜 학기를 고르면 학기별 배분안을 비교할 수 있습니다."
    e, b, m = by.get("균등형"), by.get("균형형"), by.get("최소형")
    if e and e["feasible"]:
        lines.append(f"- 균등형은 모든 학기가 비슷해 한 학기 부담은 작지만, 바쁜 학기({', '.join(f['busy_semesters'])})에도 학기당 {e['peak_credits']}학점을 들어야 합니다.")
    if b and b["feasible"]:
        lines.append(f"- 균형형은 바쁜 학기를 {', '.join(str(x) for x in b['busy_semester_credits'])}학점으로 줄이고, 나머지 학기를 평균 {b['other_semester_avg']:g}학점으로 늘려 서로 나눠 맡습니다.")
    if m and m["feasible"]:
        lines.append(f"- 최소형은 바쁜 학기를 {', '.join(str(x) for x in m['busy_semester_credits'])}학점까지 줄일 수 있지만, 나머지 학기가 평균 {m['other_semester_avg']:g}학점(학기당 최대의 {round(m['peak_ratio_of_max'] * 100)}%)으로 가장 빡빡합니다.")
    bad = [p["name"] for p in f["plans"] if not p["feasible"]]
    if bad:
        lines.append(f"- {', '.join(bad)}은 정규 학기만으로 학점이 모자라 졸업이 어렵습니다. 계절학기나 남은 학기 수를 확인하세요.")
    rec = by.get({"balanced": "균형형", "even": "균등형"}.get(f["recommended"], "균등형"))
    if rec and rec["feasible"]:
        lines.append(f"- 추천: {rec['name']}입니다. 바쁜 학기의 부담을 줄이면서도 다른 학기가 한도에 꽉 차지 않게 나눌 수 있습니다." if rec["name"] == "균형형"
                     else f"- 추천: {rec['name']}으로 시작해 보고, 바쁜 학기가 있다면 위에서 골라 비교해 보세요.")
    return "\n".join(lines)


def _call_llm_guide(facts, key):
    return _call_llm_with(GUIDE_SYSTEM, facts, key)


def explain_guide(guide, settings, call=_call_llm_guide):
    """{'source': 'ai' | 'rule', 'text': 문장, 'facts': 근거 숫자, 'note': 안내}"""
    facts = build_guide_facts(guide, settings)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return {"source": "rule", "text": guide_rule_text(facts), "facts": facts,
                "note": "AI 키(ANTHROPIC_API_KEY)가 설정되지 않아 기본 안내 문장을 보여 줍니다."}
    try:
        return {"source": "ai", "text": call(facts, key), "facts": facts, "note": ""}
    except Exception as e:
        return {"source": "rule", "text": guide_rule_text(facts), "facts": facts,
                "note": f"AI 응답을 받지 못해 기본 안내 문장을 보여 줍니다 ({type(e).__name__})."}
