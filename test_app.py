"""대출/정책자금 안내문 생성기 회귀 테스트.

실행: python -m unittest test_app -v
"""

from __future__ import annotations

import io
import os
import unittest

from pdf_parser import (
    FinancialData,
    MAX_PDF_BYTES,
    UNIT_MULTIPLIERS,
    _detect_unit,
    _find_amount,
    _find_industry,
    _to_number,
    format_amount,
    parse_pdf,
)
from templates import (
    APPROVAL,
    DEFAULT_REJECTION_REASON,
    DEFAULT_REJECTION_STRATEGY,
    GUARANTEE_REVIEW,
    REJECTION,
)


class TestNumberParsing(unittest.TestCase):
    def test_basic_integer(self):
        self.assertEqual(_to_number("1,234"), 1234)

    def test_decimal(self):
        self.assertEqual(_to_number("1,234.5"), 1234.5)

    def test_parentheses_negative(self):
        self.assertEqual(_to_number("(1,234)"), -1234)

    def test_korean_negative_marker(self):
        self.assertEqual(_to_number("△500"), -500)
        self.assertEqual(_to_number("▲500"), -500)

    def test_empty_returns_none(self):
        self.assertIsNone(_to_number(""))
        self.assertIsNone(_to_number("   "))

    def test_garbage_returns_none(self):
        self.assertIsNone(_to_number("abc"))


class TestUnitDetection(unittest.TestCase):
    def test_paren_million_won(self):
        self.assertEqual(
            _detect_unit("재 무 상 태 표\n(단위: 백만원)\n자산총계 ..."),
            "백만원",
        )

    def test_thousand_won(self):
        self.assertEqual(_detect_unit("단위: 천원"), "천원")

    def test_default_when_missing(self):
        self.assertEqual(_detect_unit("일반 텍스트"), "원")


class TestLabelSearch(unittest.TestCase):
    SAMPLE = (
        "\n업종: 제조업\n"
        "매출액               12,345\n"
        "부채총계             5,000\n"
        "자본총계             2,000\n"
        "영업이익             800\n"
        "이자비용             1,200\n"
        "단기차입금           1,500\n"
        "장기차입금           2,500\n"
    )

    def test_industry(self):
        self.assertEqual(_find_industry(self.SAMPLE), "제조업")

    def test_revenue(self):
        self.assertEqual(_find_amount(self.SAMPLE, [r"매\s*출\s*액"]), 12345)

    def test_total_liabilities(self):
        self.assertEqual(_find_amount(self.SAMPLE, [r"부\s*채\s*총\s*계"]), 5000)

    def test_total_equity(self):
        self.assertEqual(_find_amount(self.SAMPLE, [r"자\s*본\s*총\s*계"]), 2000)

    def test_operating_income(self):
        self.assertEqual(_find_amount(self.SAMPLE, [r"영\s*업\s*이\s*익"]), 800)

    def test_interest_expense(self):
        self.assertEqual(_find_amount(self.SAMPLE, [r"이\s*자\s*비\s*용"]), 1200)

    def test_no_match_returns_none(self):
        self.assertIsNone(_find_amount(self.SAMPLE, [r"존재하지않는라벨"]))


class TestFinancialDataDerived(unittest.TestCase):
    def test_debt_ratio(self):
        fd = FinancialData(total_liabilities=5000, total_equity=2000)
        self.assertAlmostEqual(fd.debt_ratio, 250.0)

    def test_debt_ratio_zero_equity_returns_none(self):
        fd = FinancialData(total_liabilities=5000, total_equity=0)
        self.assertIsNone(fd.debt_ratio)

    def test_debt_ratio_missing_returns_none(self):
        fd = FinancialData()
        self.assertIsNone(fd.debt_ratio)

    def test_interest_coverage(self):
        fd = FinancialData(operating_income=800, interest_expense=1200)
        self.assertAlmostEqual(fd.interest_coverage, 2 / 3, places=4)

    def test_interest_coverage_zero_expense_returns_none(self):
        fd = FinancialData(operating_income=800, interest_expense=0)
        self.assertIsNone(fd.interest_coverage)

    def test_total_debt_sum(self):
        fd = FinancialData(short_term_debt=1500, long_term_debt=2500)
        self.assertEqual(fd.total_debt, 4000)

    def test_total_debt_partial(self):
        fd = FinancialData(short_term_debt=1500)
        self.assertEqual(fd.total_debt, 1500)

    def test_total_debt_missing_returns_none(self):
        fd = FinancialData()
        self.assertIsNone(fd.total_debt)


class TestFormatAmount(unittest.TestCase):
    def test_none_returns_dash(self):
        self.assertEqual(format_amount(None), "-")

    def test_won_unit_under_million(self):
        self.assertEqual(format_amount(1234, "원"), "1,234원")

    def test_won_unit_in_thousands(self):
        self.assertEqual(format_amount(500_000, "원"), "500,000원")

    def test_million_won_unit_converts_to_eok(self):
        result = format_amount(12_345, "백만원")
        self.assertTrue(result.endswith("억원"), f"got {result}")

    def test_million_won_unit_man_won_range(self):
        result = format_amount(50, "백만원")
        self.assertTrue(result.endswith("만원") or result.endswith("억원"), f"got {result}")

    def test_unit_mapping_is_complete(self):
        for unit in ("원", "천원", "백만원", "억원"):
            self.assertIn(unit, UNIT_MULTIPLIERS)


class TestTemplates(unittest.TestCase):
    def test_guarantee_review_branch_substitution(self):
        out = GUARANTEE_REVIEW.format(branch="강남")
        self.assertIn("은행 강남지점을 통해 소개받았습니다", out)
        self.assertIn("은행 강남지점을 통해 대출 가능합니다", out)
        self.assertIn("✔", out)
        self.assertIn("✘", out)
        self.assertIn("⚠", out)

    def test_rejection_full_substitution(self):
        out = REJECTION.format(
            fund_name="신성장기반자금",
            industry="제조업",
            revenue="12.3억원",
            debt_ratio="450.5",
            interest_coverage="0.62",
            total_debt="5.0억원",
            reason=DEFAULT_REJECTION_REASON,
            strategy=DEFAULT_REJECTION_STRATEGY,
        )
        self.assertIn("신청하신 신성장기반자금 심사 결과", out)
        self.assertIn("- 업종: 제조업", out)
        self.assertIn("- 매출액(전년): 12.3억원", out)
        self.assertIn("- 부채비율: 450.5%", out)
        self.assertIn("- 이자보상비율: 0.62배", out)
        self.assertIn("- 총 잔액: 5.0억원", out)
        self.assertIn(DEFAULT_REJECTION_REASON, out)
        self.assertIn(DEFAULT_REJECTION_STRATEGY, out)
        self.assertIn("▶ 심사 결과: 부결", out)

    def test_approval_substitution(self):
        out = APPROVAL.format(fund_name="소상공인 정책자금", amount="3억원")
        self.assertIn("- 소상공인 정책자금, 3억원", out)
        self.assertIn("▶ 심사 결과: 승인", out)
        self.assertIn("회사에서 직접 신청하셨다고 말씀하셔야 합니다", out)

    def test_templates_preserve_decorative_lines(self):
        decoration = "━━━━━━━━━━━━━━"
        for tpl_name, tpl in (
            ("GUARANTEE_REVIEW", GUARANTEE_REVIEW),
            ("REJECTION", REJECTION),
            ("APPROVAL", APPROVAL),
        ):
            with self.subTest(template=tpl_name):
                self.assertIn(decoration, tpl)


class TestLabelBoundary(unittest.TestCase):
    """라벨 경계 (?<![가-힣]) 가 합성어 false-match를 막는지 검증."""

    def test_no_false_match_for_compound_label(self):
        # "유동성장기차입금"이 먼저 나와도 "장기차입금" 라벨이 합성어를 잡으면 안 됨
        sample = "유동성장기차입금          9,999\n장기차입금                   2,500\n"
        self.assertEqual(_find_amount(sample, [r"장\s*기\s*차\s*입\s*금"]), 2500)

    def test_no_false_match_for_prefix_label(self):
        sample = "추가부채총계        7,777\n부채총계            5,000\n"
        self.assertEqual(_find_amount(sample, [r"부\s*채\s*총\s*계"]), 5000)

    def test_label_at_line_start_still_matches(self):
        sample = "매출액      12,345\n"
        self.assertEqual(_find_amount(sample, [r"매\s*출\s*액"]), 12345)


class TestOperatingLossHandling(unittest.TestCase):
    """영업적자/0 케이스가 정확히 처리되는지 검증."""

    def test_operating_loss_returns_none_for_interest_coverage(self):
        fd = FinancialData(operating_income=-500, interest_expense=100)
        self.assertIsNone(fd.interest_coverage)
        self.assertTrue(fd.is_operating_loss)

    def test_zero_operating_income_returns_zero(self):
        # 손익분기 (영업이익 0) — 0배가 정상 출력되어야 함
        fd = FinancialData(operating_income=0, interest_expense=100)
        self.assertEqual(fd.interest_coverage, 0.0)
        self.assertFalse(fd.is_operating_loss)

    def test_no_interest_expense_returns_none(self):
        # 무차입(이자비용 0) — 분모 0 회피로 None
        fd = FinancialData(operating_income=500, interest_expense=0)
        self.assertIsNone(fd.interest_coverage)
        self.assertFalse(fd.is_operating_loss)

    def test_is_operating_loss_default_false(self):
        self.assertFalse(FinancialData().is_operating_loss)


class TestPdfSizeLimits(unittest.TestCase):
    """PDF 자원 한도 검증 (DoS 방지)."""

    def test_oversized_file_raises_value_error(self):
        big = io.BytesIO(b"%PDF-fake\n" + b"0" * (MAX_PDF_BYTES + 1))
        with self.assertRaises(ValueError) as ctx:
            parse_pdf(big)
        self.assertIn("MB", str(ctx.exception))


class TestUnitDetectionFrequency(unittest.TestCase):
    """전체 텍스트에서 단위 감지가 동작하는지."""

    def test_unit_after_2000_chars_still_detected(self):
        # head 한정이면 못 찾던 케이스 — 2000자 뒤에 단위 표기
        padding = "잡 텍스트 " * 400
        text = padding + "\n손익계산서\n(단위: 백만원)\n"
        self.assertEqual(_detect_unit(text), "백만원")

    def test_higher_frequency_unit_wins(self):
        text = (
            "재무상태표\n(단위: 백만원)\n자산총계 ...\n"
            "손익계산서\n(단위: 백만원)\n매출 ...\n"
            "주석\n(단위: 천원)\n"
        )
        self.assertEqual(_detect_unit(text), "백만원")


class TestFormatAmountNegative(unittest.TestCase):
    """자본잠식·손실 등 음수 금액 포맷팅."""

    def test_negative_eok(self):
        result = format_amount(-1.5 * 100_000_000, "원")
        self.assertTrue(result.startswith("-"), f"got {result}")
        self.assertTrue(result.endswith("억원"))

    def test_negative_man(self):
        result = format_amount(-50_000_000, "원")
        self.assertTrue(result.startswith("-"))
        self.assertTrue(result.endswith("만원") or result.endswith("억원"))

    def test_negative_won(self):
        self.assertEqual(format_amount(-1234, "원"), "-1,234원")


class TestSupabaseClientEnvValidation(unittest.TestCase):
    """supabase_client._required_env 가 환경변수 누락을 명확히 보고하는지."""

    def test_missing_env_raises_runtime_error(self):
        from supabase_client import _required_env

        original = os.environ.pop("__OMC_TEST_NO_SUCH_VAR__", None)
        try:
            with self.assertRaises(RuntimeError) as ctx:
                _required_env("__OMC_TEST_NO_SUCH_VAR__")
            self.assertIn(".env", str(ctx.exception))
        finally:
            if original is not None:
                os.environ["__OMC_TEST_NO_SUCH_VAR__"] = original

    def test_present_env_returns_value(self):
        from supabase_client import _required_env

        os.environ["__OMC_TEST_PRESENT_VAR__"] = "hello"
        try:
            self.assertEqual(_required_env("__OMC_TEST_PRESENT_VAR__"), "hello")
        finally:
            del os.environ["__OMC_TEST_PRESENT_VAR__"]


class TestDbHelpers(unittest.TestCase):
    """db 모듈의 화이트리스트와 인증 가드 검증."""

    def test_client_field_whitelist_complete(self):
        from db import CLIENT_FIELDS

        for required in (
            "name",
            "industry",
            "default_unit",
            "default_revenue",
            "default_total_liabilities",
            "default_total_equity",
            "default_operating_income",
            "default_interest_expense",
            "default_short_term_debt",
            "default_long_term_debt",
        ):
            self.assertIn(required, CLIENT_FIELDS)

    def test_history_field_whitelist_complete(self):
        from db import HISTORY_FIELDS

        for required in (
            "result_type",
            "generated_text",
            "industry_snapshot",
            "unit_snapshot",
            "revenue_snapshot",
            "debt_ratio_snapshot",
            "interest_coverage_snapshot",
            "total_debt_snapshot",
            "is_operating_loss_snapshot",
        ):
            self.assertIn(required, HISTORY_FIELDS)

    def test_user_id_raises_when_not_logged_in(self):
        import streamlit as st
        from db import _user_id

        st.session_state.pop("user", None)
        with self.assertRaises(RuntimeError) as ctx:
            _user_id()
        self.assertIn("로그인", str(ctx.exception))


class TestSanitizeFilename(unittest.TestCase):
    """업로드 파일명 표시 시 마크다운 토큰 제거."""

    def test_strips_markdown_special_chars(self):
        from app import _sanitize_filename

        self.assertEqual(_sanitize_filename("a*b_c[d].pdf"), "a_b_c_d_.pdf")

    def test_keeps_korean_and_spaces(self):
        from app import _sanitize_filename

        self.assertEqual(
            _sanitize_filename("재무제표 2025.pdf"), "재무제표 2025.pdf"
        )

    def test_truncates_long_names(self):
        from app import _sanitize_filename

        self.assertLessEqual(len(_sanitize_filename("a" * 500)), 120)


if __name__ == "__main__":
    unittest.main(verbosity=2)
