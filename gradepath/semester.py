"""학기 이름 처리: 여러 가지 표기를 하나의 형식으로 맞추고, 시간 순서로 정렬합니다.

받아들이는 표기 예: 2026-1, 26-1, 2026.1, 2026/1, 2026년 1학기, 26학년 1학기, 2026학년도 1학기,
                    2026-1학기, 20261, 2026 여름, 26-S, 2026년 겨울학기
저장 형식(표준): "2026년 1학기", "2026년 2학기", "2026년 여름학기", "2026년 겨울학기"
"""
import re

_Y = r"(\d{4}|\d{2})"
_REGULAR = [
    re.compile(rf"^{_Y}[-./_](\d)$"),                       # 2026-1, 26-1, 2026.1
    re.compile(rf"^{_Y}(?:년도?|학년도?)[-./_]?(\d)(?:학기)?$"),   # 2026년1학기, 26학년1, 2026학년도1학기
    re.compile(rf"^{_Y}[-./_]?(\d)학기$"),                   # 2026-1학기, 20261학기
    re.compile(r"^(\d{4})(\d)$"),                           # 20261
]
_SEASON = re.compile(rf"^{_Y}(?:년도?|학년도?|[-./_])?(여름|하계|summer|s|겨울|동계|winter|w)(?:계절)?(?:학기)?$", re.I)
_SUMMER = ("여름", "하계", "summer", "s")


def _year(text):
    y = int(text)
    if len(text) == 2:
        y += 2000
    return y if 1990 <= y <= 2100 else None


def parse_semester(raw):
    """(연도, 학기)로 풀어 줍니다. 학기는 1, 2 또는 '여름', '겨울'. 알아볼 수 없으면 None."""
    t = re.sub(r"\s+", "", str(raw or ""))
    if not t:
        return None
    for p in _REGULAR:
        m = p.match(t)
        if m:
            y, term = _year(m.group(1)), int(m.group(2))
            return (y, term) if y and term in (1, 2) else None
    m = _SEASON.match(t)
    if m:
        y = _year(m.group(1))
        if y:
            return y, ("여름" if m.group(2).lower() in _SUMMER else "겨울")
    return None


def normalize_semester(raw):
    """표준 형식("2026년 1학기")으로 바꿉니다. 알아볼 수 없으면 None."""
    p = parse_semester(raw)
    if p is None:
        return None
    return f"{p[0]}년 {p[1]}학기"


_ORDER = {1: 1, "여름": 2, 2: 3, "겨울": 4}


def semester_key(name):
    """정렬용 키: 시간 순서(1학기 → 여름 → 2학기 → 겨울). 알아볼 수 없는 이름은 맨 뒤로 보냅니다."""
    p = parse_semester(name)
    if p is None:
        return (1, 0, 0, str(name))
    return (0, p[0], _ORDER[p[1]], "")


def latest_regular(names):
    """입력된 학기 이름 중 가장 최근 정규 학기(1·2학기). 하나도 못 알아보면 마지막으로 입력한 학기."""
    best, best_key = None, None
    for n in names:
        p = parse_semester(n)
        if p and isinstance(p[1], int):
            k = (p[0], p[1])
            if best_key is None or k >= best_key:
                best, best_key = n, k
    if best is not None:
        return best
    return names[-1] if names else None
