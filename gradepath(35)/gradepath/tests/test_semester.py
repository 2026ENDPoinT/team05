"""semester.py 시험: 학기 표기 통일과 정렬."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from semester import latest_regular, normalize_semester, semester_key  # noqa: E402


class TestSemester(unittest.TestCase):
    def test_many_spellings_become_one(self):
        for raw in ["2026-1", "26-1", "2026.1", "2026/1", "2026년 1학기", "2026년1학기", "26학년 1학기",
                    "2026학년도 1학기", "2026-1학기", "20261", " 2026 - 1 ".replace(" - ", "-")]:
            self.assertEqual(normalize_semester(raw), "2026년 1학기", raw)
        self.assertEqual(normalize_semester("25-2"), "2025년 2학기")

    def test_seasonal(self):
        self.assertEqual(normalize_semester("2026 여름"), "2026년 여름학기")
        self.assertEqual(normalize_semester("26-S"), "2026년 여름학기")
        self.assertEqual(normalize_semester("2026년 겨울학기"), "2026년 겨울학기")

    def test_unknown_returns_none(self):
        for raw in ["", "abc", "2026", "2026-3", "2026-0", "1학기"]:
            self.assertIsNone(normalize_semester(raw), raw)

    def test_sort_chronologically(self):
        names = ["2026년 1학기", "2025년 2학기", "2025년 여름학기", "그냥메모", "2025년 1학기"]
        self.assertEqual(sorted(names, key=semester_key),
                         ["2025년 1학기", "2025년 여름학기", "2025년 2학기", "2026년 1학기", "그냥메모"])

    def test_latest_regular_ignores_seasonal_and_input_order(self):
        self.assertEqual(latest_regular(["2026년 1학기", "2025년 2학기"]), "2026년 1학기")
        self.assertEqual(latest_regular(["2025년 2학기", "2026년 여름학기"]), "2025년 2학기")
        self.assertEqual(latest_regular(["a", "b"]), "b")                  # 못 알아보면 마지막 입력
        self.assertIsNone(latest_regular([]))


if __name__ == "__main__":
    unittest.main()
