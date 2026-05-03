"""한국 재무제표 PDF에서 핵심 재무 항목을 추출한다.

추출 대상:
- 업종
- 매출액(전년)
- 부채총계, 자본총계 → 부채비율 산출
- 영업이익, 이자비용 → 이자보상비율 산출
- 단기차입금, 장기차입금 → 차입금 총잔액 산출

단위 자동 감지(원/천원/백만원/억원)도 시도한다. 추출 실패 항목은
None으로 두고 UI에서 사용자가 직접 수정할 수 있게 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import IO, Optional

import pdfplumber


UNIT_MULTIPLIERS = {
    "원": 1,
    "천원": 1_000,
    "백만원": 1_000_000,
    "억원": 100_000_000,
}

# 보안: PDF 자원 한도 (DoS 방지)
MAX_PDF_BYTES = 10 * 1024 * 1024  # 10MB
MAX_PDF_PAGES = 100
# 정규식: 라벨 다음 숫자까지 허용하는 최대 문자 수 (회사별 표 간격 차이 대응)
LABEL_LOOKAHEAD_CHARS = 40


@dataclass
class FinancialData:
    industry: str = ""
    revenue: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_equity: Optional[float] = None
    operating_income: Optional[float] = None
    interest_expense: Optional[float] = None
    short_term_debt: Optional[float] = None
    long_term_debt: Optional[float] = None
    detected_unit: str = "원"
    raw_text: str = field(default="", repr=False)
    extraction_log: list[str] = field(default_factory=list)

    @property
    def debt_ratio(self) -> Optional[float]:
        if (
            self.total_liabilities is not None
            and self.total_equity is not None
            and self.total_equity > 0
        ):
            return (self.total_liabilities / self.total_equity) * 100
        return None

    @property
    def interest_coverage(self) -> Optional[float]:
        # 영업적자(< 0)는 이자보상비율이 의미 없음 → None 반환.
        # 영업이익 0(손익분기)은 0배로 정상 산출.
        if (
            self.operating_income is not None
            and self.operating_income >= 0
            and self.interest_expense is not None
            and self.interest_expense > 0
        ):
            return self.operating_income / self.interest_expense
        return None

    @property
    def is_operating_loss(self) -> bool:
        """영업적자 여부 (안내문에서 별도 표기용)."""
        return self.operating_income is not None and self.operating_income < 0

    @property
    def total_debt(self) -> Optional[float]:
        parts = [v for v in (self.short_term_debt, self.long_term_debt) if v is not None]
        return sum(parts) if parts else None


def _to_number(text: str) -> Optional[float]:
    s = text.replace(",", "").replace(" ", "").strip()
    if not s:
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if s.startswith("△") or s.startswith("▲"):
        s = "-" + s[1:]
    try:
        return float(s)
    except ValueError:
        return None


def _detect_unit(text: str) -> str:
    """텍스트 전체에서 '단위:' 표기 출현 빈도가 가장 높은 단위를 선택.

    재무상태표(앞)와 손익계산서(뒤)가 다른 단위를 쓰는 경우를 위해
    head 2000자 한정이 아니라 본문 전체를 스캔.
    """
    counts: dict[str, int] = {}
    # 더 긴 단위가 짧은 단위에 포함되지 않도록 순서 보존
    for unit in ("억원", "백만원", "천원", "원"):
        pattern = r"단\s*위[\s:：]*\(?\s*" + unit
        counts[unit] = len(re.findall(pattern, text))
    # 양수 카운트가 있으면 최다 빈도 단위, 동률이면 더 큰 단위 우선
    best = max(counts.items(), key=lambda kv: (kv[1], UNIT_MULTIPLIERS[kv[0]]))
    return best[0] if best[1] > 0 else "원"


def _find_amount(text: str, label_patterns: list[str]) -> Optional[float]:
    """라벨 정규식 뒤에 등장하는 첫 번째 숫자를 추출.

    `(?<![가-힣])` 한글 경계로 합성어 false-match 방지
    (예: "유동성장기차입금" 안의 "장기차입금" 매칭 차단).
    """
    boundary = r"(?<![가-힣])"
    lookahead = r"[^\d\-△▲(]{0," + str(LABEL_LOOKAHEAD_CHARS) + r"}"
    number = r"([(\-△▲]?\s*[\d,]+(?:\.\d+)?\)?)"
    for label in label_patterns:
        regex = boundary + label + lookahead + number
        m = re.search(regex, text)
        if m:
            num = _to_number(m.group(1))
            if num is not None:
                return num
    return None


def _find_industry(text: str) -> str:
    patterns = [
        r"업\s*종[\s:：]*([^\n\r]{1,40})",
        r"업\s*태[\s:：]*([^\n\r]{1,40})",
        r"사\s*업\s*종\s*목[\s:：]*([^\n\r]{1,40})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            value = m.group(1).strip()
            value = re.split(r"[\t]{2,}|\s{3,}", value)[0].strip()
            if value:
                return value
    return ""


def parse_pdf(file: IO) -> FinancialData:
    # 보안: 파일 크기 제한 (PDF bomb / DoS 방지)
    try:
        file.seek(0, 2)
        size = file.tell()
        file.seek(0)
    except (AttributeError, OSError):
        size = None
    if size is not None and size > MAX_PDF_BYTES:
        raise ValueError(
            f"PDF 크기가 한도({MAX_PDF_BYTES // (1024 * 1024)}MB)를 초과합니다."
        )

    text_parts: list[str] = []
    with pdfplumber.open(file) as pdf:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise ValueError(
                f"PDF 페이지 수({len(pdf.pages)})가 한도({MAX_PDF_PAGES})를 초과합니다."
            )
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    text = "\n".join(text_parts)

    data = FinancialData(raw_text=text)
    data.detected_unit = _detect_unit(text)

    data.industry = _find_industry(text)
    if data.industry:
        data.extraction_log.append(f"업종: '{data.industry}'")

    field_map: list[tuple[str, str, list[str]]] = [
        ("revenue", "매출액", [r"매\s*출\s*액", r"매\s*출\s*수\s*익", r"영\s*업\s*수\s*익"]),
        ("total_liabilities", "부채총계", [r"부\s*채\s*총\s*계", r"부\s*채\s*합\s*계"]),
        ("total_equity", "자본총계", [r"자\s*본\s*총\s*계", r"자\s*기\s*자\s*본\s*총\s*계", r"자\s*본\s*합\s*계"]),
        ("operating_income", "영업이익", [r"영\s*업\s*이\s*익", r"영\s*업\s*손\s*익"]),
        ("interest_expense", "이자비용", [r"이\s*자\s*비\s*용", r"금\s*융\s*비\s*용"]),
        ("short_term_debt", "단기차입금", [r"단\s*기\s*차\s*입\s*금"]),
        ("long_term_debt", "장기차입금", [r"장\s*기\s*차\s*입\s*금"]),
    ]

    for attr, label, patterns in field_map:
        value = _find_amount(text, patterns)
        if value is not None:
            setattr(data, attr, value)
            data.extraction_log.append(f"{label}: {value:,.0f}")
        else:
            data.extraction_log.append(f"{label}: 추출 실패")

    # 보안 L1: 민감한 PDF 원문이 세션에 누적되지 않도록 짧은 진단용 발췌만 유지
    data.raw_text = text[:1024]
    return data


def format_amount(value: Optional[float], unit: str = "원") -> str:
    """안내문에 들어갈 금액 표기를 한국식으로 포맷."""
    if value is None:
        return "-"
    multiplier = UNIT_MULTIPLIERS.get(unit, 1)
    won = value * multiplier
    abs_won = abs(won)
    if abs_won >= 100_000_000:
        eok = won / 100_000_000
        return f"{eok:,.1f}억원"
    if abs_won >= 1_000_000:
        man = won / 10_000
        return f"{man:,.0f}만원"
    return f"{won:,.0f}원"
