"""Supabase 클라이언트 싱글턴 (Streamlit 세션 단위).

환경변수는 import 시점이 아니라 실제 클라이언트가 필요해질 때 lazy 검증한다.
이렇게 해야 .env 없이도 단위 테스트가 깨지지 않는다.
"""

from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv
from supabase import Client, create_client


# .env 파일이 있으면 환경변수에 로드 (없으면 OS 환경변수만 사용)
load_dotenv()


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"환경변수 '{name}' 이(가) 비어 있습니다. "
            ".env 파일을 만들고 SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY 를 설정하세요. "
            "(.env.example 참고)"
        )
    return value


def get_client() -> Client:
    """현재 Streamlit 세션에 바인딩된 Supabase 클라이언트.

    같은 브라우저 세션에서 재실행 시 동일 클라이언트 재사용 → 로그인 세션이 유지됨.
    클라이언트 인스턴스가 세션별로 분리되므로 멀티유저 사용 시에도 토큰 충돌 없음.
    """
    if "supabase_client" not in st.session_state:
        st.session_state.supabase_client = create_client(
            _required_env("SUPABASE_URL"),
            _required_env("SUPABASE_PUBLISHABLE_KEY"),
        )
    return st.session_state.supabase_client
