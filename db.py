"""Supabase 테이블 CRUD — clients(고객사 기초정보) + notice_history(이력).

RLS가 사용자 격리를 책임지므로 코드는 `user_id` 필터링을 명시하지 않아도 안전하지만,
insert 시 user_id는 직접 채워야 한다 (RLS check 통과용).
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from supabase_client import get_client


# ─── 내부 헬퍼 ────────────────────────────────────────────────


def _user_id() -> str:
    user = st.session_state.get("user")
    if user is None:
        raise RuntimeError("로그인되지 않았습니다.")
    uid = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
    if not uid:
        raise RuntimeError("사용자 ID를 확인할 수 없습니다.")
    return uid


# ─── clients ─────────────────────────────────────────────────


CLIENT_FIELDS = [
    "name",
    "industry",
    "business_no",
    "default_unit",
    "default_revenue",
    "default_total_liabilities",
    "default_total_equity",
    "default_operating_income",
    "default_interest_expense",
    "default_short_term_debt",
    "default_long_term_debt",
    "notes",
]


def list_clients() -> list[dict[str, Any]]:
    resp = (
        get_client()
        .from_("clients")
        .select("*")
        .order("name")
        .execute()
    )
    return resp.data or []


def get_client_by_id(client_id: str) -> dict[str, Any] | None:
    resp = (
        get_client()
        .from_("clients")
        .select("*")
        .eq("id", client_id)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def create_client_row(payload: dict[str, Any]) -> dict[str, Any]:
    payload = {k: payload.get(k) for k in CLIENT_FIELDS}
    payload["user_id"] = _user_id()
    resp = get_client().from_("clients").insert(payload).execute()
    return (resp.data or [{}])[0]


def update_client_row(client_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    update = {k: payload[k] for k in CLIENT_FIELDS if k in payload}
    resp = (
        get_client()
        .from_("clients")
        .update(update)
        .eq("id", client_id)
        .execute()
    )
    return (resp.data or [{}])[0]


def delete_client_row(client_id: str) -> None:
    get_client().from_("clients").delete().eq("id", client_id).execute()


# ─── notice_history ──────────────────────────────────────────


HISTORY_FIELDS = [
    "client_id",
    "result_type",
    "fund_name",
    "branch",
    "approval_amount",
    "rejection_reason",
    "rejection_strategy",
    "industry_snapshot",
    "unit_snapshot",
    "revenue_snapshot",
    "debt_ratio_snapshot",
    "interest_coverage_snapshot",
    "total_debt_snapshot",
    "is_operating_loss_snapshot",
    "generated_text",
]


def save_history(payload: dict[str, Any]) -> dict[str, Any]:
    row = {k: payload.get(k) for k in HISTORY_FIELDS}
    row["user_id"] = _user_id()
    resp = get_client().from_("notice_history").insert(row).execute()
    return (resp.data or [{}])[0]


def list_history(limit: int = 100) -> list[dict[str, Any]]:
    resp = (
        get_client()
        .from_("notice_history")
        .select("*, clients(name)")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def delete_history_row(history_id: str) -> None:
    get_client().from_("notice_history").delete().eq("id", history_id).execute()
