"""Supabase Auth 흐름 + Streamlit 통합."""

from __future__ import annotations

from typing import Any

import streamlit as st

from supabase_client import get_client


def current_user() -> Any | None:
    """로그인된 사용자 객체 (없으면 None)."""
    return st.session_state.get("user")


def is_authed() -> bool:
    return current_user() is not None


def _restore_session_if_present() -> None:
    """st.session_state에 저장된 토큰을 클라이언트에 재주입 (rerun 사이 유지)."""
    sess = st.session_state.get("session")
    if not sess:
        return
    try:
        client = get_client()
        access = getattr(sess, "access_token", None) or sess.get("access_token")
        refresh = getattr(sess, "refresh_token", None) or sess.get("refresh_token")
        if access and refresh:
            client.auth.set_session(access, refresh)
    except Exception:
        # 토큰 만료 등 어떤 사유든 발생 시 세션 삭제 → 로그인 화면으로
        st.session_state.pop("user", None)
        st.session_state.pop("session", None)


def login_form() -> None:
    st.title("🔐 로그인")
    st.caption("이메일과 비밀번호로 로그인하세요. 처음이면 회원가입 탭에서 등록.")

    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("이메일", autocomplete="email")
            password = st.text_input(
                "비밀번호", type="password", autocomplete="current-password"
            )
            submit = st.form_submit_button("로그인", type="primary")
        if submit:
            if not email or not password:
                st.error("이메일과 비밀번호를 모두 입력하세요.")
                return
            try:
                client = get_client()
                resp = client.auth.sign_in_with_password(
                    {"email": email, "password": password}
                )
                if resp.session and resp.user:
                    st.session_state.user = resp.user
                    st.session_state.session = resp.session
                    st.success("로그인 완료!")
                    st.rerun()
                else:
                    st.error("로그인 실패: 이메일/비밀번호를 확인하세요.")
            except Exception as exc:  # noqa: BLE001 - Supabase 다양한 오류
                st.error(f"로그인 오류: {exc}")

    with tab_signup:
        with st.form("signup_form"):
            email_s = st.text_input("이메일", key="signup_email")
            password_s = st.text_input(
                "비밀번호 (8자 이상)", type="password", key="signup_pw1"
            )
            password_s2 = st.text_input(
                "비밀번호 확인", type="password", key="signup_pw2"
            )
            submit_s = st.form_submit_button("회원가입", type="primary")
        if submit_s:
            if not email_s or not password_s:
                st.error("이메일과 비밀번호를 모두 입력하세요.")
                return
            if password_s != password_s2:
                st.error("비밀번호가 일치하지 않습니다.")
                return
            if len(password_s) < 8:
                st.error("비밀번호는 8자 이상이어야 합니다.")
                return
            try:
                client = get_client()
                resp = client.auth.sign_up(
                    {"email": email_s, "password": password_s}
                )
                if resp.user is None:
                    st.error("회원가입 실패: 응답 비어 있음")
                    return
                if resp.session:
                    # 이메일 인증 미설정 시 즉시 로그인됨
                    st.session_state.user = resp.user
                    st.session_state.session = resp.session
                    st.success("회원가입 + 로그인 완료!")
                    st.rerun()
                else:
                    st.info(
                        "회원가입 완료. 등록한 이메일로 인증 메일을 확인하시고, "
                        "인증 후 다시 로그인 탭에서 로그인하세요."
                    )
            except Exception as exc:  # noqa: BLE001
                st.error(f"회원가입 오류: {exc}")


def logout() -> None:
    try:
        get_client().auth.sign_out()
    except Exception:
        pass
    for key in ("user", "session", "supabase_client"):
        st.session_state.pop(key, None)
    st.rerun()


def auth_gate() -> bool:
    """로그인 안 된 사용자에게 로그인 화면을 보여주고 False 반환.

    True 반환 시 호출자는 이어서 메인 UI를 렌더해도 안전.
    """
    _restore_session_if_present()
    if is_authed():
        return True
    login_form()
    return False
