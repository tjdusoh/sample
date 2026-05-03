"""대출/정책자금 안내문 자동 생성 Streamlit 앱.

Phase 5+: Supabase Auth + clients(고객사) + notice_history(이력) 통합.
"""

from __future__ import annotations

import re

import streamlit as st

import db
from auth import auth_gate, current_user, logout
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


# ─── 세션 상태 초기화 ─────────────────────────────────────────


def _ensure_state() -> None:
    if "financial_data" not in st.session_state:
        st.session_state.financial_data = FinancialData()
    if "parsed_filename" not in st.session_state:
        st.session_state.parsed_filename = ""
    if "last_generated" not in st.session_state:
        st.session_state.last_generated = None


def _reset_session() -> None:
    """세션에 남은 재무제표 정보를 명시적으로 폐기 (보안 L1)."""
    st.session_state.financial_data = FinancialData()
    st.session_state.parsed_filename = ""
    st.session_state.last_generated = None


# ─── 사이드바: 사용자 + 고객사 ────────────────────────────────


def _render_sidebar() -> str | None:
    """사이드바를 그리고, 선택된 client_id (또는 None) 반환."""
    user = current_user()
    selected_client_id: str | None = None

    with st.sidebar:
        st.markdown(f"👤 **{getattr(user, 'email', '사용자')}**")
        col_a, col_b = st.columns(2)
        if col_a.button("세션 초기화"):
            _reset_session()
            st.rerun()
        if col_b.button("로그아웃"):
            logout()

        st.divider()
        st.markdown("### 📒 고객사")

        try:
            clients = db.list_clients()
        except Exception as exc:  # noqa: BLE001
            st.error(f"고객사 조회 오류: {exc}")
            clients = []

        options = ["(직접 입력)"] + [c["name"] for c in clients]
        selection = st.selectbox(
            "저장된 고객사 선택",
            options,
            help="선택 시 해당 회사의 저장된 기본값으로 폼이 채워집니다.",
        )

        if selection != "(직접 입력)":
            picked = next((c for c in clients if c["name"] == selection), None)
            if picked:
                selected_client_id = picked["id"]
                if st.button("이 회사 정보를 폼에 불러오기", type="primary"):
                    _apply_client_to_form(picked)
                    st.rerun()
                with st.expander("이 회사 정보 수정/삭제"):
                    _render_client_edit(picked)

        with st.expander("➕ 현재 폼을 새 고객사로 저장"):
            _render_client_create()

    return selected_client_id


def _apply_client_to_form(client: dict) -> None:
    """선택된 고객사의 기본값을 financial_data에 주입."""
    fd = FinancialData(
        industry=client.get("industry") or "",
        revenue=client.get("default_revenue"),
        total_liabilities=client.get("default_total_liabilities"),
        total_equity=client.get("default_total_equity"),
        operating_income=client.get("default_operating_income"),
        interest_expense=client.get("default_interest_expense"),
        short_term_debt=client.get("default_short_term_debt"),
        long_term_debt=client.get("default_long_term_debt"),
        detected_unit=client.get("default_unit") or "원",
    )
    st.session_state.financial_data = fd


def _render_client_create() -> None:
    fd: FinancialData = st.session_state.financial_data
    with st.form("create_client"):
        name = st.text_input("회사명*")
        business_no = st.text_input("사업자번호 (선택)")
        notes = st.text_area("메모 (선택)", height=60)
        submit = st.form_submit_button("새 고객사 저장", type="primary")
    if submit:
        if not name.strip():
            st.error("회사명은 필수입니다.")
            return
        try:
            db.create_client_row(
                {
                    "name": name.strip(),
                    "industry": fd.industry or None,
                    "business_no": business_no.strip() or None,
                    "default_unit": fd.detected_unit,
                    "default_revenue": fd.revenue,
                    "default_total_liabilities": fd.total_liabilities,
                    "default_total_equity": fd.total_equity,
                    "default_operating_income": fd.operating_income,
                    "default_interest_expense": fd.interest_expense,
                    "default_short_term_debt": fd.short_term_debt,
                    "default_long_term_debt": fd.long_term_debt,
                    "notes": notes.strip() or None,
                }
            )
            st.success(f"'{name}' 저장됨")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"저장 오류: {exc}")


def _render_client_edit(client: dict) -> None:
    fd: FinancialData = st.session_state.financial_data
    st.caption(f"마지막 수정: {client.get('updated_at', '-')}")
    if st.button("현재 폼 값으로 이 회사 업데이트", key=f"upd_{client['id']}"):
        try:
            db.update_client_row(
                client["id"],
                {
                    "industry": fd.industry or None,
                    "default_unit": fd.detected_unit,
                    "default_revenue": fd.revenue,
                    "default_total_liabilities": fd.total_liabilities,
                    "default_total_equity": fd.total_equity,
                    "default_operating_income": fd.operating_income,
                    "default_interest_expense": fd.interest_expense,
                    "default_short_term_debt": fd.short_term_debt,
                    "default_long_term_debt": fd.long_term_debt,
                },
            )
            st.success("업데이트 완료")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"업데이트 오류: {exc}")
    if st.button("🗑️ 이 회사 삭제", key=f"del_{client['id']}"):
        try:
            db.delete_client_row(client["id"])
            st.success("삭제 완료")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"삭제 오류: {exc}")


# ─── 메인: PDF 업로드 ─────────────────────────────────────────


def _render_uploader() -> None:
    st.subheader("1. 재무제표 PDF 업로드")
    uploaded = st.file_uploader("재무제표 PDF 파일", type=["pdf"])
    col_a, col_b = st.columns([1, 3])
    with col_a:
        clicked = st.button(
            "PDF에서 값 추출", type="primary", disabled=uploaded is None
        )
    with col_b:
        if uploaded is not None:
            st.write("업로드됨:")
            st.code(_sanitize_filename(uploaded.name), language=None)

    if clicked and uploaded is not None:
        try:
            data = parse_pdf(uploaded)
        except ValueError as exc:
            st.error(str(exc))
            return
        except Exception:  # noqa: BLE001
            st.error("PDF를 읽을 수 없습니다. 텍스트 PDF인지 확인하거나 다른 파일로 시도해 주세요.")
            return
        st.session_state.financial_data = data
        st.session_state.parsed_filename = uploaded.name
        st.success("재무제표에서 값을 추출했습니다. 아래에서 확인/수정하세요.")
        with st.expander("추출 로그"):
            for line in data.extraction_log:
                st.text(line)


# ─── 메인: 재무수치 폼 ────────────────────────────────────────


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


# ─── 메인: 결과 유형 선택 + 안내문 생성 ─────────────────────


def _render_result_section(data: FinancialData, selected_client_id: str | None) -> None:
    st.subheader("3. 결과 유형 선택 및 안내문 생성")

    result_type = st.radio(
        "심사 결과 유형",
        options=["보증기관 추가 검토", "정책자금 부결", "정책자금 승인"],
        horizontal=True,
    )

    output = ""
    history_payload: dict | None = None

    if result_type == "보증기관 추가 검토":
        branch = st.text_input("은행 지점명", value="", placeholder="예: 강남")
        if branch:
            output = GUARANTEE_REVIEW.format(branch=branch)
            history_payload = {"branch": branch.strip()}
        else:
            st.info("지점명을 입력하면 안내문이 생성됩니다.")

    elif result_type == "정책자금 부결":
        col_a, _ = st.columns(2)
        with col_a:
            fund_name = st.text_input(
                "자금명",
                value="",
                placeholder="예: 중소벤처기업진흥공단 신성장기반자금",
            )
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
            history_payload = {
                "fund_name": fund_name.strip(),
                "rejection_reason": reason.strip(),
                "rejection_strategy": strategy.strip(),
            }
        else:
            st.info("자금명을 입력하면 안내문이 생성됩니다.")

    else:  # 정책자금 승인
        col_a, col_b = st.columns(2)
        with col_a:
            fund_name = st.text_input("자금명", value="")
        with col_b:
            amount = st.text_input("승인 금액", value="", placeholder="예: 3억원")
        if fund_name and amount:
            output = APPROVAL.format(
                fund_name=fund_name.strip(), amount=amount.strip()
            )
            history_payload = {
                "fund_name": fund_name.strip(),
                "approval_amount": amount.strip(),
            }
        else:
            st.info("자금명과 승인 금액을 입력하면 안내문이 생성됩니다.")

    if output:
        st.markdown("#### 생성된 안내문")
        st.text_area(
            "복사해 사용하세요",
            value=output,
            height=420,
            label_visibility="collapsed",
        )
        col_dl, col_save = st.columns(2)
        with col_dl:
            st.download_button(
                "텍스트 파일로 저장",
                data=output.encode("utf-8"),
                file_name=f"{result_type.replace(' ', '_')}.txt",
                mime="text/plain",
            )
        with col_save:
            if st.button("이력에 저장", type="primary"):
                _save_to_history(
                    result_type=result_type,
                    output=output,
                    data=data,
                    selected_client_id=selected_client_id,
                    extra=history_payload or {},
                )


def _save_to_history(
    *,
    result_type: str,
    output: str,
    data: FinancialData,
    selected_client_id: str | None,
    extra: dict,
) -> None:
    payload = {
        "client_id": selected_client_id,
        "result_type": result_type,
        "industry_snapshot": data.industry or None,
        "unit_snapshot": data.detected_unit,
        "revenue_snapshot": data.revenue,
        "debt_ratio_snapshot": data.debt_ratio,
        "interest_coverage_snapshot": data.interest_coverage,
        "total_debt_snapshot": data.total_debt,
        "is_operating_loss_snapshot": data.is_operating_loss,
        "generated_text": output,
        **extra,
    }
    try:
        db.save_history(payload)
        st.success("이력에 저장됨")
    except Exception as exc:  # noqa: BLE001
        st.error(f"저장 오류: {exc}")


# ─── 이력 조회 탭 ─────────────────────────────────────────────


def _render_history_tab() -> None:
    st.subheader("📜 안내문 생성 이력")
    try:
        rows = db.list_history(limit=100)
    except Exception as exc:  # noqa: BLE001
        st.error(f"이력 조회 오류: {exc}")
        return

    if not rows:
        st.info("아직 저장된 이력이 없습니다. '안내문 생성' 탭에서 안내문을 만든 후 [이력에 저장] 버튼을 눌러보세요.")
        return

    for row in rows:
        client_name = (row.get("clients") or {}).get("name") or "-"
        title = f"{row['created_at'][:19]} · {row['result_type']} · {client_name}"
        with st.expander(title):
            st.text(row["generated_text"])
            col_dl, col_del = st.columns(2)
            with col_dl:
                st.download_button(
                    "다시 다운로드",
                    data=row["generated_text"].encode("utf-8"),
                    file_name=f"{row['result_type'].replace(' ', '_')}_{row['id'][:8]}.txt",
                    mime="text/plain",
                    key=f"dl_{row['id']}",
                )
            with col_del:
                if st.button("이 이력 삭제", key=f"del_h_{row['id']}"):
                    try:
                        db.delete_history_row(row["id"])
                        st.success("삭제됨")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"삭제 오류: {exc}")


# ─── 메인 ─────────────────────────────────────────────────────


def main() -> None:
    if not auth_gate():
        return

    _ensure_state()
    selected_client_id = _render_sidebar()

    st.title("📄 대출 / 정책자금 안내문 자동 생성기")

    tab_gen, tab_hist = st.tabs(["🆕 안내문 생성", "📜 이력 조회"])

    with tab_gen:
        _render_uploader()
        st.divider()
        data = _render_financials_form()
        st.divider()
        _render_result_section(data, selected_client_id)

    with tab_hist:
        _render_history_tab()


if __name__ == "__main__":
    main()
