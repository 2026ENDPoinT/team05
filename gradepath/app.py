"""GradePath 웹 서버 (Flask)

역할: 화면(브라우저)이 보내는 요청을 받아서 calc.py의 계산 함수를 부르고,
결과를 JSON으로 돌려줍니다. 계산 자체는 모두 calc.py에 있습니다.

실행:  python app.py   ->  브라우저에서 http://127.0.0.1:5000
"""
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, Response, g, jsonify, render_template, request

import calc
import os
import threading
import json
import importer
import storage
from semester import normalize_semester, semester_key
from rules import (EXTRA_CREDIT_RULE, GRADE_ORDER, GRADE_POINTS, GRADING_MODES, MODE_LABELS,
                   PASS_FAIL_GRADES, UNCERTAINTY, rule_summary)

ALL_GRADES = list(GRADE_POINTS) + PASS_FAIL_GRADES
COOKIE = "gp_uid"

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # 배포 환경(프록시 뒤)에서 https 여부를 올바르게 알아봄
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0      # 예전 화면 파일이 브라우저에 남아 새 기능이 안 보이는 문제 방지


@app.context_processor
def static_version():
    """static 파일 주소에 수정 시각을 붙여, 파일이 바뀌면 브라우저가 항상 새로 받게 합니다."""
    def v(name):
        try:
            return int(os.path.getmtime(os.path.join(app.static_folder, name)))
        except OSError:
            return 0
    return {"sv": v}
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024   # 업로드 파일은 1MB까지
storage.init()   # DB 파일·테이블 생성, 예전 JSON 데이터가 있으면 한 번만 이전


def _warm_up():
    """엑셀 라이브러리는 처음 불러올 때 느리므로, 서버가 켜질 때 미리 불러오고 양식 파일도 만들어 둡니다."""
    try:
        importer.template_xlsx()
    except Exception:
        pass


threading.Thread(target=_warm_up, daemon=True).start()


# ---------- 사용자 구분 (브라우저별 데이터) ----------

@app.before_request
def identify_user():
    uid = request.cookies.get(COOKIE)
    g.new_uid = not storage.valid_uid(uid)
    g.uid = storage.new_uid() if g.new_uid else uid


@app.after_request
def remember_user(resp):
    if g.get("new_uid") and request.path != "/healthz":
        resp.set_cookie(COOKIE, g.uid, max_age=60 * 60 * 24 * 730, httponly=True, samesite="Lax", secure=request.is_secure)
    return resp


def load():
    return storage.load(g.uid)


def save(data):
    storage.save(g.uid, data)


# ---------- 입력 검사 도우미 ----------

class BadInput(Exception):
    pass


def need_text(body, key, label, max_len=40):
    v = str(body.get(key, "")).strip()
    if not v:
        raise BadInput(f"{label}: 값을 입력해 주세요.")
    return v[:max_len]


def need_int(body, key, label, lo, hi):
    raw = body.get(key)
    try:
        if isinstance(raw, bool):
            raise ValueError
        if isinstance(raw, float):
            if not raw.is_integer():
                raise BadInput(f"{label}: 소수가 아닌 정수로 입력해 주세요.")
            raw = int(raw)
        v = int(str(raw).strip())          # "3.5" 같은 문자열은 여기서 오류
    except BadInput:
        raise
    except (TypeError, ValueError):
        raise BadInput(f"{label}: 숫자(정수)로 입력해 주세요.")
    if not lo <= v <= hi:
        raise BadInput(f"{label}: {lo}~{hi} 사이로 입력해 주세요.")
    return v


def need_float(body, key, label, lo, hi):
    try:
        v = float(body.get(key))
    except (TypeError, ValueError):
        raise BadInput(f"{label}: 숫자로 입력해 주세요.")
    if v != v or not lo <= v <= hi:      # v != v 는 NaN 검사
        raise BadInput(f"{label}: {lo}~{hi} 사이로 입력해 주세요.")
    return v


def need_choice(body, key, label, choices):
    v = body.get(key)
    if v not in choices:
        raise BadInput(f"{label}: 올바르지 않은 값입니다.")
    return v


@app.errorhandler(413)
def handle_too_large(e):
    return jsonify({"error": "파일이 너무 큽니다. 1MB 이하 파일을 올려 주세요."}), 413


@app.errorhandler(BadInput)
def handle_bad_input(e):
    return jsonify({"error": str(e)}), 400


def need_semester(body, key="semester", label="학기"):
    """2026-1, 26-1, 2026년 1학기 같은 표기는 모두 "2026년 1학기"로 통일합니다.
    알아볼 수 없는 이름(예: 편입 전 학기)은 입력한 그대로 저장합니다."""
    raw = need_text(body, key, label)
    return normalize_semester(raw) or raw


def parse_completed(body):
    return {
        "semester": need_semester(body),
        "name": need_text(body, "name", "과목명", 30),
        "credit": need_int(body, "credit", "학점", 1, 6),
        "type": need_choice(body, "type", "구분", ("major", "lib")),
        "required": body.get("required") is True,
        "grade": need_choice(body, "grade", "성적", ALL_GRADES),
    }


def opt_max(body, key, label):
    """만점 값. 비어 있거나 0 이하이면 100점 만점으로 봅니다 (기본값 100)."""
    raw = body.get(key)
    if raw in (None, ""):
        return 100.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise BadInput(f"{label}: 숫자로 입력해 주세요.")
    if v != v or v <= 0:
        return 100.0
    if v > 10000:
        raise BadInput(f"{label}: 10000 이하로 입력해 주세요.")
    return v


def need_upto(body, key, label, hi, lo=0.0):
    """lo 이상 hi 이하의 숫자 (hi는 보통 그 항목의 만점). 넘으면 '값은 {hi} 이하여야 합니다'."""
    try:
        v = float(body.get(key))
    except (TypeError, ValueError):
        raise BadInput(f"{label}: 숫자로 입력해 주세요.")
    if v != v:
        raise BadInput(f"{label}: 숫자로 입력해 주세요.")
    if v > hi:
        raise BadInput(f"{label}: 값은 {hi:g} 이하여야 합니다.")
    if v < lo:
        raise BadInput(f"{label}: 값은 {lo:g} 이상이어야 합니다.")
    return v


def parse_current(body):
    fin_ratio = None                                  # 기말고사 반영 비율과 만점 (점수는 기말고사 이후에만 입력)
    fin_max = 100.0
    fin_score = None
    if body.get("fin_ratio") not in (None, ""):
        fin_ratio = need_float(body, "fin_ratio", "기말고사 반영 비율", 0.01, 100)
        fin_max = opt_max(body, "fin_max", "기말고사 만점")
    if body.get("fin_score") not in (None, ""):
        if fin_ratio is None:
            raise BadInput("기말고사 점수: 기말고사 평가 비중을 함께 입력해 주세요.")
        fin_score = need_upto(body, "fin_score", "기말고사 점수", fin_max)
    items = []
    raw_items = body.get("items") or []
    if not isinstance(raw_items, list) or len(raw_items) > 8:
        raise BadInput("평가 항목은 최대 8개까지 입력할 수 있습니다.")
    for it in raw_items:
        if not isinstance(it, dict):
            raise BadInput("평가 항목 형식이 올바르지 않습니다.")
        imax = opt_max(it, "max", "항목 만점")
        item = {"name": need_text(it, "name", "항목 이름", 20),
                "score": need_upto(it, "score", "항목 점수", imax),
                "ratio": need_float(it, "ratio", "항목 반영 비율", 0.01, 100)}
        if imax != 100.0:
            item["max"] = imax
        items.append(item)
    exam_ratio = None
    if fin_ratio is not None or items:
        exam_ratio = need_float(body, "exam_ratio", "중간고사 반영 비율", 0.01, 100)
        if exam_ratio + (fin_ratio or 0) + sum(i["ratio"] for i in items) > 100.0001:
            raise BadInput("반영 비율의 합이 100%를 넘을 수 없습니다")
    extra = {}
    if exam_ratio is not None:
        extra["exam_ratio"] = exam_ratio
    if fin_ratio is not None:
        extra["fin_ratio"] = fin_ratio
        if fin_max != 100.0:
            extra["fin_max"] = fin_max
        if fin_score is not None:
            extra["fin_score"] = fin_score * 100.0 / fin_max      # 계산은 모두 100점 만점 환산 값으로 저장
    if items:
        extra["items"] = items
    max_score = opt_max(body, "max_score", "중간고사 만점")
    if max_score != 100.0:
        extra["max_score"] = max_score
    return {**extra,
        "name": need_text(body, "name", "과목명", 30),
        "credit": need_int(body, "credit", "학점", 1, 6),
        "type": need_choice(body, "type", "구분", ("major", "lib")),
        "required": body.get("required") is True,
        "score": need_upto(body, "score", "중간고사 점수", max_score),
        "mean": need_upto(body, "mean", "평균", max_score),
        "std": need_upto(body, "std", "표준편차", max_score / 2, 0.01),   # 소수점 둘째 자리까지 입력 가능
        "grading": need_choice(body, "grading", "평가 방식", GRADING_MODES),
    }


# ---------- 화면 ----------

@app.get("/healthz")
def healthz():
    """배포 서비스가 서버 상태를 확인하는 주소"""
    return jsonify({"ok": True})


@app.get("/")
def index():
    return render_template("index.html")


# ---------- 상태 ----------

@app.get("/api/state")
def get_state():
    data = load()
    data["completed"] = sorted(data["completed"], key=lambda c: semester_key(c["semester"]))   # 학기 순서대로
    data["grades"] = GRADE_ORDER
    data["pass_fail_grades"] = PASS_FAIL_GRADES
    data["grading_modes"] = GRADING_MODES
    data["mode_labels"] = MODE_LABELS
    data["uncertainty"] = UNCERTAINTY
    return jsonify(data)


@app.get("/api/rules")
def get_rules():
    return jsonify(rule_summary())


@app.get("/api/summary")
def get_summary():
    data = load()
    done = data["completed"]
    s = data["settings"]
    semesters = {}
    for c in done:
        semesters.setdefault(c["semester"], []).append(c)
    semesters = dict(sorted(semesters.items(), key=lambda kv: semester_key(kv[0])))
    by_sem = [{"name": name,
               "gpa": calc.calc_gpa(cs),
               "credits": sum(c["credit"] for c in cs),
               "earned": calc.earned_credits(cs)}
              for name, cs in semesters.items()]
    earned = calc.earned_credits(done)
    major = calc.earned_credits([c for c in done if c["type"] == "major"])
    return jsonify({
        "gpa": calc.calc_gpa(done),
        "registered": sum(c["credit"] for c in done),   # 등록 학점 (F·P/F 과목 포함 전체)
        "earned": earned,
        "major": major,
        "lib": calc.earned_credits([c for c in done if c["type"] == "lib"]),
        "semesters": by_sem,
        "burden": calc.graduation_burden(earned, s),
        "extra_credit": calc.extra_credit_status(done, s),
        "extra_rule": EXTRA_CREDIT_RULE,
        "required": s["total_credits_required"],
        "major_required": s["major_credits_required"],
        "major_remaining": max(0, s["major_credits_required"] - major),
    })


# ---------- 설정 / 모드 / 사용방법 ----------

@app.put("/api/settings")
def put_settings():
    body = request.get_json(silent=True) or {}
    data = load()
    s = data["settings"]
    s["total_credits_required"] = need_int(body, "total_credits_required", "졸업 학점", 1, 300)
    s["major_credits_required"] = need_int(body, "major_credits_required", "전공 졸업학점", 0, 200)
    s["max_credits_per_semester"] = need_int(body, "max_credits_per_semester", "학기당 최대 학점", 1, 40)
    s["max_credits_per_year"] = need_int(body, "max_credits_per_year", "학년도 최대 학점", 1, 80)
    s["remaining_semesters"] = need_int(body, "remaining_semesters", "남은 학기 수", 0, 18)
    s["extra_semesters"] = need_int(body, "extra_semesters", "추가 학기 수", 0, 10) if "extra_semesters" in body else 0
    if s["remaining_semesters"] < s["extra_semesters"]:
        raise BadInput("추가 학기 수: 남은 학기 수보다 클 수 없습니다.")
    s["seasonal_plan_credits"] = need_int(body, "seasonal_plan_credits", "계절학기 계획 학점", 0, 60)
    s["target_gpa"] = need_float(body, "target_gpa", "목표 평균 학점", 0, 4.5)
    s["retake_cap"] = need_choice(body, "retake_cap", "재수강 최고 성적", GRADE_POINTS)
    s["retake_max_prior"] = need_choice(body, "retake_max_prior", "재수강 가능 성적", GRADE_POINTS)
    data["settings_done"] = True          # 설정을 직접 확인·저장했음 (처음 접속 안내에 사용)
    save(data)
    return jsonify({"ok": True})


@app.put("/api/mode")
def put_mode():
    body = request.get_json(silent=True) or {}
    storage.set_mode(g.uid, need_choice(body, "mode", "시점", MODE_LABELS))      # 시점 한 칸만 바꿈 (전체 저장보다 빠름)
    return jsonify({"ok": True})


@app.put("/api/onboarded")
def put_onboarded():
    """사용방법 안내의 '다시 보지 않기'를 기억합니다."""
    body = request.get_json(silent=True) or {}
    data = load()
    data["onboarded"] = body.get("onboarded") is True
    save(data)
    return jsonify({"ok": True})


# ---------- 지난 학기 성적 ----------

@app.post("/api/completed")
def add_completed():
    item = parse_completed(request.get_json(silent=True) or {})
    item["id"] = storage.new_id()
    data = load()
    data["completed"].append(item)
    save(data)
    return jsonify({"ok": True, "id": item["id"]})


@app.put("/api/completed/<cid>")
def edit_completed(cid):
    item = parse_completed(request.get_json(silent=True) or {})
    data = load()
    for i, c in enumerate(data["completed"]):
        if c["id"] == cid:
            data["completed"][i] = {**item, "id": cid}
            save(data)
            return jsonify({"ok": True})
    raise BadInput("수정할 과목을 찾을 수 없습니다.")


@app.delete("/api/completed/<cid>")
def delete_completed(cid):
    data = load()
    data["completed"] = [c for c in data["completed"] if c["id"] != cid]
    save(data)
    return jsonify({"ok": True})


# ---------- 스프레드시트로 지난 학기 성적 불러오기 ----------

def course_key(c):
    """같은 과목인지 비교하는 기준 (학기, 과목명, 학점, 성적이 모두 같으면 중복)"""
    return (c["semester"], c["name"], c["credit"], c["grade"])


@app.get("/api/completed/template.csv")
def import_template():
    return Response(importer.template_csv(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=polaris_template.csv"})


@app.get("/api/completed/template.xlsx")
def import_template_xlsx():
    try:
        data = importer.template_xlsx()
    except ImportError:
        raise BadInput("서버에 openpyxl이 설치되어 있지 않습니다. CSV 양식을 받아 주세요.")
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=polaris_template.xlsx",
                             "Cache-Control": "public, max-age=3600"})


@app.post("/api/import/preview")
def import_preview():
    """파일을 읽어 어떤 과목이 들어올지 미리 보여 줍니다. 아직 저장하지 않습니다."""
    f = request.files.get("file")
    if f is None or not f.filename:
        raise BadInput("파일을 선택해 주세요.")
    try:
        rows, errors = importer.parse_file(f.filename, f.read())
    except ValueError as e:
        raise BadInput(str(e))
    existing = {course_key(c) for c in load()["completed"]}
    seen = set()
    for r in rows:
        k = course_key(r)
        r["duplicate"] = k in existing or k in seen
        seen.add(k)
    return jsonify({"rows": rows, "errors": errors})


@app.post("/api/completed/bulk")
def add_completed_bulk():
    """미리 보기에서 확인한 과목들을 한꺼번에 저장합니다 (한 줄이라도 잘못되면 아무것도 저장하지 않음)."""
    body = request.get_json(silent=True) or {}
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        raise BadInput("추가할 과목이 없습니다.")
    if len(rows) > importer.MAX_ROWS:
        raise BadInput(f"한 번에 {importer.MAX_ROWS}과목까지만 추가할 수 있습니다.")
    data = load()
    existing = {course_key(c) for c in data["completed"]}
    added = skipped = 0
    for r in rows:
        try:
            item = parse_completed(r if isinstance(r, dict) else {})
        except BadInput as e:
            raise BadInput(f"{r.get('line', '?') if isinstance(r, dict) else '?'}번째 줄 - {e}")
        k = course_key(item)
        if k in existing:
            skipped += 1
            continue
        existing.add(k)
        item["id"] = storage.new_id()
        data["completed"].append(item)
        added += 1
    save(data)
    return jsonify({"ok": True, "added": added, "skipped": skipped})


# ---------- 이번 학기 과목 ----------

@app.post("/api/current")
def add_current():
    item = parse_current(request.get_json(silent=True) or {})
    item["id"] = storage.new_id()
    data = load()
    data["current"].append(item)
    save(data)
    return jsonify({"ok": True, "id": item["id"]})


@app.put("/api/current/<cid>")
def edit_current(cid):
    item = parse_current(request.get_json(silent=True) or {})
    data = load()
    for i, c in enumerate(data["current"]):
        if c["id"] == cid:
            data["current"][i] = {**item, "id": cid}
            save(data)
            return jsonify({"ok": True})
    raise BadInput("수정할 과목을 찾을 수 없습니다.")


@app.delete("/api/current/<cid>")
def delete_current(cid):
    data = load()
    data["current"] = [c for c in data["current"] if c["id"] != cid]
    save(data)
    return jsonify({"ok": True})


# ---------- 분석 ----------

@app.get("/api/predict")
def api_predict():
    data = load()
    if not data["current"]:
        raise BadInput("이번 학기 과목을 먼저 입력해 주세요.")
    return jsonify(calc.predict_semester(data["completed"], data["current"], data["settings"]))


@app.get("/api/chart-data")
def api_chart_data():
    """그래프에 쓰는 데이터. ?format=csv 면 엑셀용 CSV로 내려줍니다."""
    import charts
    data = load()
    if request.args.get("format") == "csv":
        return Response(charts.chart_csv(data), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=gradepath_chart_data.csv"})
    return Response(json.dumps(charts.chart_data(data), ensure_ascii=False, indent=2),
                    mimetype="application/json; charset=utf-8",
                    headers={"Content-Disposition": "inline; filename=gradepath_chart_data.json"}
                    if request.args.get("download") else {})


@app.post("/api/explain")
def api_explain():
    """계산 결과(숫자)는 코드가 만들고, LLM은 그 숫자를 문장으로만 풀어 씁니다."""
    import llm
    body = request.get_json(silent=True) or {}
    data = load()
    ids = [c["id"] for c in data["current"]]
    cid = need_choice(body, "course_id", "과목", ids)
    target = need_choice(body, "target_grade", "목표 학점", [g for g in GRADE_POINTS if g != "F"])
    course = next(c for c in data["current"] if c["id"] == cid)
    try:
        return jsonify(llm.explain(course, target))
    except ValueError as e:
        raise BadInput(str(e))


def parse_busy(raw):
    """바쁜 학기 번호 목록 ('7,8' 또는 [7, 8]). None이면 기본값(4학년), 빈 값이면 바쁜 학기 없음."""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x.strip() != ""]
    if not isinstance(raw, list) or len(raw) > 12:
        raise BadInput("바쁜 학기 형식이 올바르지 않습니다.")
    try:
        return [int(x) for x in raw]
    except (TypeError, ValueError):
        raise BadInput("바쁜 학기는 학기 번호(숫자)로 보내 주세요.")


@app.get("/api/guide")
def api_guide():
    data = load()
    busy = parse_busy(request.args.get("busy"))
    return jsonify(calc.life_guide(data["completed"], data["current"], data["settings"], busy))


@app.post("/api/explain-guide")
def api_explain_guide():
    """학기별 학점 배분안 설명. 숫자는 코드가 계산하고, LLM은 문장만 씁니다."""
    import llm
    body = request.get_json(silent=True) or {}
    data = load()
    guide = calc.life_guide(data["completed"], data["current"], data["settings"], parse_busy(body.get("busy")))
    return jsonify(llm.explain_guide(guide, data["settings"]))


@app.post("/api/simulate")
def api_simulate():
    """목표 GPA 시뮬레이션: 고른 과목이 각 등급일 때의 학기·누적 평균 학점"""
    body = request.get_json(silent=True) or {}
    data = load()
    ids = [c["id"] for c in data["current"]]
    if not ids:
        raise BadInput("이번 학기 과목을 먼저 입력해 주세요.")
    cid = need_choice(body, "course_id", "과목", ids)
    return jsonify(calc.simulate_course_grades(data["completed"], data["current"], cid, data["settings"]))


@app.post("/api/final-estimate")
def api_final_estimate():
    """기말고사 이후(성적 확정 전): 최종 총점으로 예상 학점과 학점 경계까지의 거리"""
    body = request.get_json(silent=True) or {}
    data = load()
    ids = [c["id"] for c in data["current"]]
    if not ids:
        raise BadInput("현 학기 교과목을 먼저 등록해 주세요.")
    cid = need_choice(body, "course_id", "과목", ids)
    course = next(c for c in data["current"] if c["id"] == cid)
    if course.get("fin_score") is None:
        raise BadInput("이 과목은 기말고사 점수가 없습니다. 위 '현 학기 교과목 등록'에서 기말고사 점수를 입력해 주세요.")
    total, mean, std = calc.eff_stats(course)      # 등록한 중간·기말·기타 항목 점수를 100점 환산해 합친 값
    if course["grading"] == "absolute":
        mean = std = 0.0
    return jsonify(calc.final_estimate(data["completed"], data["current"], cid, data["settings"], round(total, 2), mean, std))


@app.post("/api/withdraw")
def api_withdraw():
    body = request.get_json(silent=True) or {}
    data = load()
    ids = [c["id"] for c in data["current"]]
    if not ids:
        raise BadInput("이번 학기 과목을 먼저 입력해 주세요.")
    cid = need_choice(body, "course_id", "과목", ids)
    return jsonify(calc.analyze_withdraw(data["completed"], data["current"], cid, data["settings"]))


@app.get("/api/retake/candidates")
def api_retake_candidates():
    data = load()
    return jsonify({"candidates": calc.retake_candidates(data["completed"], data["current"], data["settings"]),
                    "retake_max_prior": data["settings"]["retake_max_prior"]})


@app.post("/api/retake")
def api_retake():
    """source가 completed면 지난 학기 성적, current면 이번 학기 예상 성적을 '기존 성적'으로 보고 비교합니다."""
    body = request.get_json(silent=True) or {}
    data = load()
    s = data["settings"]
    source = need_choice(body, "source", "과목 종류", ("completed", "current"))
    done = data["completed"]
    if source == "completed":
        pool = done
    else:
        pool = data["current"]
    if not pool:
        raise BadInput("과목을 먼저 입력해 주세요.")
    cid = need_choice(body, "course_id", "과목", [c["id"] for c in pool])
    picked = next(c for c in pool if c["id"] == cid)

    if source == "current":
        # 이번 학기 과목은 현재 점수 기준 예상 성적이 나온 것으로 보고 지난 성적 목록에 임시로 추가
        picked = {"id": picked["id"], "name": picked["name"], "credit": picked["credit"],
                  "grade": calc.grade_at(picked, 0.0), "required": picked.get("required", False)}
        done = done + [picked]

    if picked["grade"] not in GRADE_POINTS:
        raise BadInput("P/F(합격/불합격) 과목은 재수강 비교를 지원하지 않습니다.")
    if not calc.is_retakable(picked["grade"], s):
        raise BadInput(f"재수강은 {s['retake_max_prior']} 이하 성적만 가능합니다.")

    other_credits = need_int(body, "other_credits", "함께 듣는 다른 과목 학점", 0, 30) if body.get("other_credits") not in (None, "") else 0
    other_avg = need_float(body, "other_avg_point", "다른 과목 예상 평균 평점", 0, 4.5) if body.get("other_avg_point") not in (None, "") else 3.0
    result = calc.analyze_retake(done, cid, s, other_credits, other_avg)
    result["source"] = source
    return jsonify(result)


if __name__ == "__main__":
    # 내 컴퓨터에서만 쓸 때는 기본값 그대로. 배포하면 HOST/PORT 환경변수가 자동으로 쓰입니다.
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=False)
