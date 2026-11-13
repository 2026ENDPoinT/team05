"""스프레드시트(.xlsx / .csv)에서 지난 학기 성적을 읽어 옵니다.

이 파일은 '파일 -> 과목 목록' 변환만 맡습니다. 값이 올바른지의 최종 검사는 app.py의 parse_completed가 다시 합니다.
첫 줄(머리글)에 학기, 과목명, 학점, 구분, 필수, 성적 칸이 있어야 하고, 칸 이름은 아래 별칭도 알아봅니다.
"""
import csv
import functools
import io

from semester import normalize_semester

MAX_ROWS = 200

ALIASES = {
    "semester": ("학기", "수강학기", "이수학기", "년도학기", "연도학기"),
    "name": ("과목명", "교과목명", "과목", "교과목", "강의명"),
    "credit": ("학점", "이수학점"),
    "type": ("구분", "이수구분", "전공교양", "전공/교양", "분류"),
    "required": ("필수", "필수여부"),
    "grade": ("성적", "등급", "성적등급", "취득성적"),
}
HEADER_TEXT = {k: v[0] for k, v in ALIASES.items()}

# 양식의 예시 줄: 과목명이 "(예시)"로 시작하면 불러올 때 자동으로 건너뜁니다 (지우지 않고 올려도 가짜 과목이 들어가지 않음)
EXAMPLE_MARK = "(예시)"
TEMPLATE_ROWS = [
    ["학기", "과목명", "학점", "구분", "필수", "성적"],
    ["2025-1", EXAMPLE_MARK + " 프로그래밍입문", 3, "전공", "필수", "A0"],
    ["2025년 1학기", EXAMPLE_MARK + " 미분적분학", 3, "교양", "", "B+"],
    ["2025-2", EXAMPLE_MARK + " 선형대수학", 3, "전공", "", "P"],
]
TEMPLATE_NOTE = ("※ '(예시)' 줄은 보기용입니다. 지우거나 덮어써서 본인 과목을 입력하세요. "
                 "학기는 2025-1, 2025년 1학기 어느 쪽으로 적어도 됩니다.")

VALID_GRADES = ("A+", "A0", "B+", "B0", "C+", "C0", "D+", "D0", "F", "P", "NP")
TRUE_WORDS = ("o", "y", "yes", "true", "1", "필수", "예", "v", "✓", "●", "○")


def _norm_header(v):
    return str(v or "").replace(" ", "").replace("\n", "").strip().lower()


def _cell(v):
    """칸 값을 문자열로. 3.0 같은 실수는 3으로 정리합니다."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def template_csv():
    buf = io.StringIO()
    csv.writer(buf).writerows(TEMPLATE_ROWS)
    return "﻿" + buf.getvalue()     # 엑셀에서 한글이 깨지지 않도록 BOM 포함


@functools.lru_cache(maxsize=1)
def template_xlsx():
    """입력하기 쉬운 엑셀 양식: 안내 줄, 예시 줄(회색), 구분·필수·성적·학점 칸에 드롭다운/입력 제한."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "지난 학기 성적"
    ws.merge_cells("A1:F1")
    ws["A1"] = TEMPLATE_NOTE
    ws["A1"].font = Font(color="6B7490", size=10)
    ws["A1"].alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[1].height = 34
    for j, h in enumerate(TEMPLATE_ROWS[0], start=1):
        c = ws.cell(row=2, column=j, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="27355F")
        c.alignment = Alignment(horizontal="center")
    for i, row in enumerate(TEMPLATE_ROWS[1:], start=3):
        for j, v in enumerate(row, start=1):
            c = ws.cell(row=i, column=j, value=v if v != "" else None)
            c.font = Font(italic=True, color="8A91A8")
            c.fill = PatternFill("solid", fgColor="EEF1F7")
    for col, w in zip("ABCDEF", (16, 26, 8, 10, 10, 10)):
        ws.column_dimensions[col].width = w
    last = 2 + MAX_ROWS
    lists = {"D": '"전공,교양"', "E": '"필수"', "F": '"A+,A0,B+,B0,C+,C0,D+,D0,F,P,불합격"'}
    for col, formula in lists.items():
        dv = DataValidation(type="list", formula1=formula, allow_blank=True)
        dv.error, dv.errorTitle = "목록에서 골라 주세요.", "잘못된 값"
        ws.add_data_validation(dv)
        dv.add(f"{col}3:{col}{last}")
    dv = DataValidation(type="whole", operator="between", formula1="1", formula2="6", allow_blank=True)
    dv.error, dv.errorTitle = "학점은 1~6 사이 정수로 입력해 주세요.", "잘못된 값"
    ws.add_data_validation(dv)
    dv.add(f"C3:C{last}")
    ws.freeze_panes = "A3"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------
# 파일 -> 표(행 목록)
# ------------------------------------------------------------------

def _read_csv(data):
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("CSV 글자 인코딩을 읽을 수 없습니다. 엑셀에서 'CSV UTF-8'로 저장하거나 .xlsx로 올려 주세요.")
    sample = text[:2000]
    delim = "\t" if sample.count("\t") > sample.count(",") else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim)]


def _read_xlsx(data):
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ValueError("서버에 openpyxl이 설치되어 있지 않습니다. 'pip install -r requirements.txt'를 실행하거나 CSV로 올려 주세요.")
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ValueError("엑셀 파일을 열 수 없습니다. 파일이 손상됐거나 암호가 걸려 있을 수 있습니다.")
    ws = wb.worksheets[0]                  # 첫 번째 시트만 읽음
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


def read_table(filename, data):
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        return _read_xlsx(data)
    if name.endswith(".csv") or name.endswith(".tsv") or name.endswith(".txt"):
        return _read_csv(data)
    if name.endswith(".xls"):
        raise ValueError("예전 형식(.xls)은 지원하지 않습니다. 엑셀에서 '다른 이름으로 저장' → .xlsx 또는 CSV로 저장해 주세요.")
    raise ValueError(".xlsx 또는 .csv 파일을 올려 주세요.")


# ------------------------------------------------------------------
# 표 -> 과목 목록
# ------------------------------------------------------------------

def _find_header(table):
    """머리글 줄을 찾아 {필드: 열번호}를 돌려줍니다 (위쪽 10줄 안에서 찾음)."""
    for i, row in enumerate(table[:10]):
        heads = [_norm_header(c) for c in row]
        cols = {}
        for field, names in ALIASES.items():
            for n in names:
                key = _norm_header(n)
                if key in heads:
                    cols[field] = heads.index(key)
                    break
        if "name" in cols and "grade" in cols and "credit" in cols:
            return i, cols
    return None, None


PF_ALIASES = {"합격": "P", "불합격": "NP", "F(P/F)": "NP", "F(PF)": "NP", "P/F불합격": "NP", "PF불합격": "NP"}


def _grade(raw):
    g = raw.replace("⁰", "0").replace("＋", "+").replace(" ", "").upper()
    g = PF_ALIASES.get(g, g)
    if g in VALID_GRADES:
        return g, None
    if g in ("A", "B", "C", "D"):
        return None, f"'{raw}'는 A+/A0처럼 구체적으로 적어 주세요"
    return None, f"알 수 없는 성적 '{raw}'"


def _type_and_required(type_raw, req_raw):
    t = type_raw.replace(" ", "")
    required = req_raw.strip().lower() in TRUE_WORDS or "필수" in t
    if "전공" in t:
        return "major", required, None
    if t in ("", "교양", "교양선택", "교양필수", "일반선택", "기초필수") or "교양" in t:
        return "lib", required, None
    return None, required, f"알 수 없는 구분 '{type_raw}' (전공/교양 중 하나로 적어 주세요)"


def parse_table(table):
    """표(행 목록)를 읽어 (rows, errors)를 돌려줍니다.

    rows:   [{"line": 엑셀 줄 번호, "semester", "name", "credit", "type", "required", "grade"}, ...]
    errors: [{"line": 줄 번호, "message": ...}, ...]  (오류가 있는 줄은 rows에 넣지 않음)
    """
    head_i, cols = _find_header(table)
    if head_i is None:
        raise ValueError("머리글 줄을 찾지 못했습니다. 첫 줄에 '학기, 과목명, 학점, 구분, 필수, 성적' 칸이 있어야 합니다. (양식 받기 참고)")
    if "semester" not in cols:
        raise ValueError("'학기' 칸이 없습니다. 양식의 첫 줄을 확인해 주세요.")

    rows, errors = [], []
    body = table[head_i + 1:]
    if len(body) > MAX_ROWS:
        raise ValueError(f"한 번에 {MAX_ROWS}줄까지만 불러올 수 있습니다.")

    def get(row, field):
        i = cols.get(field)
        return _cell(row[i]) if i is not None and i < len(row) else ""

    for offset, row in enumerate(body):
        line = head_i + 2 + offset                       # 엑셀에서 보이는 줄 번호
        if not any(_cell(c) for c in row):
            continue                                     # 빈 줄 건너뜀
        problems = []
        semester, name = get(row, "semester"), get(row, "name")
        if name.startswith(EXAMPLE_MARK) or name.startswith("예시)"):
            continue                                     # 양식의 예시 줄은 건너뜀
        if not semester:
            problems.append("학기가 비어 있음")
        else:
            semester = normalize_semester(semester) or semester     # 2025-1 → 2025년 1학기 (알아볼 수 없으면 그대로)
        if not name:
            problems.append("과목명이 비어 있음")
        credit_raw = get(row, "credit")
        try:
            credit = int(float(credit_raw.replace("학점", "")))
            if credit != float(credit_raw.replace("학점", "")) or not 1 <= credit <= 6:
                raise ValueError
        except ValueError:
            credit = None
            problems.append(f"학점 '{credit_raw}'은 1~6 사이 정수여야 함")
        grade, gerr = _grade(get(row, "grade"))
        if gerr:
            problems.append(gerr)
        typ, required, terr = _type_and_required(get(row, "type"), get(row, "required"))
        if terr:
            problems.append(terr)
        if problems:
            errors.append({"line": line, "message": ", ".join(problems)})
        else:
            rows.append({"line": line, "semester": semester[:40], "name": name[:30], "credit": credit,
                         "type": typ, "required": required, "grade": grade})
    if not rows and not errors:
        raise ValueError("불러올 과목이 없습니다. 머리글 아래에 본인 과목을 입력해 주세요. ('(예시)' 줄은 불러오지 않습니다)")
    return rows, errors


def parse_file(filename, data):
    return parse_table(read_table(filename, data))
