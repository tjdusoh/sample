"""대출/정책자금 안내문 자동 생성 Streamlit 앱."""

from __future__ import annotations

import re

import streamlit as st

from pdf_parser import (
    FinancialData,
    UNIT_MULTIPLIERS,
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


def _sanitize_filename(name: str) -> str:
    """업로드 파일명에 포함된 마크다운/제어문자를 안전 표시용으로 정리."""
    return re.sub(r"[^\w.\- ]", "_", name)[:120]


st.set_page_config(page_title="대출/정책자금 안내문 생성기", layout="wide")

st.title("📄 대출 / 정책자금 안내문 자동 생성기")
st.caption(
    "재무제표 PDF를 업로드하고 결과 유형을 선택하면 안내문 본문이 자동 작성됩니다. "
    "추출 실패 시 항목을 직접 수정할 수 있습니다."
)


def _ensure_state() -> None:
    if "financial_data" not in st.session_state:
        st.session_state.financial_data = FinancialData()
    if "parsed_filename" not in st.session_state:
        st.session_state.parsed_filename = ""


def _reset_session() -> None:
    """세션에 남은 재무제표 정보를 명시적으로 폐기 (보안 L1)."""
    st.session_state.financial_data = FinancialData()
    st.session_state.parsed_filename = ""


def _render_uploader() -> None:
    st.subheader("1. 재무제표 PDF 업로드")
    uploaded = st.file_uploader("재무제표 PDF 파일", type=["pdf"])
    col_a, col_b = st.columns([1, 3])
    with col_a:
        clicked = st.button("PDF에서 값 추출", type="primary", disabled=uploaded is None)
    with col_b:
        if uploaded is not None:
            st.write("업로드됨:")
            st.code(_sanitize_filename(uploaded.name), language=None)

    if clicked and uploaded is not None:
        try:
            data = parse_pdf(uploaded)
        except ValueError as exc:
            # MAX_PDF_BYTES / MAX_PDF_PAGES 초과 등 사용자 메시지 안전한 경우
            st.error(str(exc))
            return
        except Exception:  # noqa: BLE001 - PDF 라이브러리 다양한 오류
            # 내부 경로/스택 노출 방지: 일반화된 메시지만 표시
            st.error("PDF를 읽을 수 없습니다. 텍스트 PDF인지 확인하거나 다른 파일로 시도해 주세요.")
            return
        st.session_state.financial_data = data
        st.session_state.parsed_filename = uploaded.name
        st.success("재무제표에서 값을 추출했습니다. 아래에서 확인/수정하세요.")
        with st.expander("추출 로그"):
            for line in data.extraction_log:
                st.text(line)


def _render_financials_form() -> FinancialData:
    st.subheader("2. 추출값 확인 및 수정")
    data: FinancialData = st.session_state.financial_data

    unit = st.selectbox(
        "재무제표 단위",
        list(UNIT_MULTIPLIERS.keys()),
        index=list(UNIT_MULTIPLIERS.keys()).index(data.detected_unit)
        if data.detected_unit in UNIT_MULTIPLIERS
        else 0,
        help="PDF에 표시된 금액 단위를 선택하세요. 안내문 출력 시 환산에 사용됩니다.",
    )

    # value=None: 미입력/추출 실패 상태를 0과 명확히 구분 (Streamlit 1.30+).
    # 사용자가 의도적으로 0(영업적자, 무이자 등)을 입력하면 0.0으로 전달되어
    # interest_coverage 계산이 정확히 동작.
    def _val(x: float | None) -> float | None:
        return float(x) if x is not None else None

    col1, col2 = st.columns(2)
    with col1:
        industry = st.text_input("업종", value=data.industry)
        revenue = st.number_input(
            "매출액 (전년)", value=_val(data.revenue), step=1.0, format="%.0f"
        )
        total_liabilities = st.number_input(
            "부채총계", value=_val(data.total_liabilities), step=1.0, format="%.0f"
        )
        total_equity = st.number_input(
            "자본총계", value=_val(data.total_equity), step=1.0, format="%.0f"
        )
    with col2:
        operating_income = st.number_input(
            "영업이익 (적자는 음수)",
            value=_val(data.operating_income),
            step=1.0,
            format="%.0f",
        )
        interest_expense = st.number_input(
            "이자비용", value=_val(data.interest_expense), step=1.0, format="%.0f"
        )
        short_term_debt = st.number_input(
            "단기차입금", value=_val(data.short_term_debt), step=1.0, format="%.0f"
        )
        long_term_debt = st.number_input(
            "장기차입금", value=_val(data.long_term_debt), step=1.0, format="%.0f"
        )

    updated = FinancialData(
        industry=industry.strip(),
        revenue=revenue,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        operating_income=operating_income,
        interest_expense=interest_expense,
        short_term_debt=short_term_debt,
        long_term_debt=long_term_debt,
        detected_unit=unit,
        # rerun 시 추출 로그·원문이 손실되지 않도록 보존
        raw_text=data.raw_text,
        extraction_log=data.extraction_log,
    )

    metric_cols = st.columns(3)
    metric_cols[0].metric(
        "부채비율",
        f"{updated.debt_ratio:,.1f}%" if updated.debt_ratio is not None else "-",
    )
    if updated.interest_coverage is not None:
        ic_display = f"{updated.interest_coverage:,.2f}배"
    elif updated.is_operating_loss:
        ic_display = "영업적자"
    else:
        ic_display = "-"
    metric_cols[1].metric("이자보상비율", ic_display)
    metric_cols[2].metric(
        "차입금 총잔액",
        format_amount(updated.total_debt, unit) if updated.total_debt is not None else "-",
    )

    st.session_state.financial_data = updated
    return updated


def _render_result_section(data: FinancialData) -> None:
    st.subheader("3. 결과 유형 선택 및 안내문 생성")

    result_type = st.radio(
        "심사 결과 유형",
        options=["보증기관 추가 검토", "정책자금 부결", "정책자금 승인"],
        horizontal=True,
    )

    output = ""

    if result_type == "보증기관 추가 검토":
        branch = st.text_input("은행 지점명", value="", placeholder="예: 강남")
        if branch:
            output = GUARANTEE_REVIEW.format(branch=branch)
        else:
            st.info("지점명을 입력하면 안내문이 생성됩니다.")

    elif result_type == "정책자금 부결":
        col_a, col_b = st.columns(2)
        with col_a:
            fund_name = st.text_input("자금명", value="", placeholder="예: 중소벤처기업진흥공단 신성장기반자금")
        with col_b:
            unit = data.detected_unit
        reason = st.text_area("부결 사유", value=DEFAULT_REJECTION_REASON, height=80)
        strategy = st.text_area("향후 전략", value=DEFAULT_REJECTION_STRATEGY, height=80)

        if fund_name:
            if data.interest_coverage is not None:
                ic_text = f"{data.interest_coverage:,.2f}"
            elif data.is_operating_loss:
                ic_text = "영업적자"
            else:
                ic_text = "-"
            output = REJECTION.format(
                fund_name=fund_name,
                industry=data.industry or "-",
                revenue=format_amount(data.revenue, data.detected_unit),
                debt_ratio=f"{data.debt_ratio:,.1f}" if data.debt_ratio is not None else "-",
                interest_coverage=ic_text,
                total_debt=format_amount(data.total_debt, data.detected_unit),
                reason=reason.strip() or DEFAULT_REJECTION_REASON,
                strategy=strategy.strip() or DEFAULT_REJECTION_STRATEGY,
            )
        else:
            st.info("자금명을 입력하면 안내문이 생성됩니다.")

    else:  # 정책자금 승인
        col_a, col_b = st.columns(2)
        with col_a:
            fund_name = st.text_input("자금명", value="")
        with col_b:
            amount = st.text_input("승인 금액", value="", placeholder="예: 3억원")
        if fund_name and amount:
            output = APPROVAL.format(fund_name=fund_name.strip(), amount=amount.strip())
        else:
            st.info("자금명과 승인 금액을 입력하면 안내문이 생성됩니다.")

    if output:
        st.markdown("#### 생성된 안내문")
        st.text_area("복사해 사용하세요", value=output, height=420, label_visibility="collapsed")
        st.download_button(
            "텍스트 파일로 저장",
            data=output.encode("utf-8"),
            file_name=f"{result_type.replace(' ', '_')}.txt",
            mime="text/plain",
        )


def main() -> None:
    _ensure_state()
    with st.sidebar:
        st.markdown("### 세션 관리")
        st.caption("업로드한 재무제표 정보는 브라우저 세션 메모리에만 보관되며, 디스크에 저장되지 않습니다.")
        if st.button("세션 초기화 (재무제표 폐기)"):
            _reset_session()
            st.rerun()
    _render_uploader()
    st.divider()
    data = _render_financials_form()
    st.divider()
    _render_result_section(data)


if __name__ == "__main__":
    main()
