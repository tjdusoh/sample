-- ============================================================
-- 대출/정책자금 안내문 자동 생성기 — Supabase 스키마
-- 실행: Supabase Dashboard → SQL Editor → New query → 전체 붙여넣고 RUN
-- 이 SQL은 멱등(반복 실행 가능)하도록 작성됨 (drop if exists / create or replace).
-- ============================================================

-- ─── 1. updated_at 자동 갱신용 헬퍼 함수 ───────────────────────
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;


-- ─── 2. clients (고객사 기초정보) ──────────────────────────────
-- 자주 쓰는 회사 정보 + 마지막 재무수치를 저장해두고 안내문 생성 시 빠르게 채움.
create table if not exists public.clients (
  id                       uuid primary key default gen_random_uuid(),
  user_id                  uuid not null references auth.users(id) on delete cascade,
  name                     text not null,
  industry                 text,
  business_no              text,                     -- 사업자등록번호 (선택)
  default_unit             text default '원',
  default_revenue          numeric,
  default_total_liabilities numeric,
  default_total_equity     numeric,
  default_operating_income numeric,
  default_interest_expense numeric,
  default_short_term_debt  numeric,
  default_long_term_debt   numeric,
  notes                    text,
  created_at               timestamptz default now(),
  updated_at               timestamptz default now()
);

create index if not exists clients_user_id_idx on public.clients(user_id);
create index if not exists clients_user_name_idx on public.clients(user_id, name);

-- 같은 사용자 안에서 동일 사업자번호 중복 방지 (사업자번호가 있는 행에만 적용)
create unique index if not exists clients_user_business_no_uidx
  on public.clients(user_id, business_no)
  where business_no is not null;

drop trigger if exists clients_set_updated_at on public.clients;
create trigger clients_set_updated_at
  before update on public.clients
  for each row execute function public.set_updated_at();


-- ─── 3. notice_history (안내문 생성 이력) ──────────────────────
-- 안내문은 생성 시점의 재무 스냅샷과 함께 immutable 로그로 보관.
create table if not exists public.notice_history (
  id                          uuid primary key default gen_random_uuid(),
  user_id                     uuid not null references auth.users(id) on delete cascade,
  client_id                   uuid references public.clients(id) on delete set null,
  result_type                 text not null
    check (result_type in ('보증기관 추가 검토', '정책자금 부결', '정책자금 승인')),

  -- 사용자 입력 필드
  fund_name                   text,
  branch                      text,
  approval_amount             text,
  rejection_reason            text,
  rejection_strategy          text,

  -- 생성 당시의 재무 스냅샷 (이력 immutability 보장)
  industry_snapshot           text,
  unit_snapshot               text,
  revenue_snapshot            numeric,
  debt_ratio_snapshot         numeric,
  interest_coverage_snapshot  numeric,
  total_debt_snapshot         numeric,
  is_operating_loss_snapshot  boolean default false,

  -- 최종 출력 텍스트
  generated_text              text not null,

  created_at                  timestamptz default now()
);

create index if not exists notice_history_user_id_idx
  on public.notice_history(user_id);
create index if not exists notice_history_created_at_idx
  on public.notice_history(created_at desc);
create index if not exists notice_history_client_id_idx
  on public.notice_history(client_id);


-- ─── 4. Row-Level Security (RLS) 활성화 ───────────────────────
-- 핵심: 각 사용자는 자기 데이터만 보고/쓰고/지울 수 있음.
-- service_role 키는 RLS 우회 가능 → 절대 클라이언트에 노출 X.
alter table public.clients          enable row level security;
alter table public.notice_history   enable row level security;


-- ─── 5. clients RLS 정책 ──────────────────────────────────────
drop policy if exists "clients_select_own"  on public.clients;
drop policy if exists "clients_insert_own"  on public.clients;
drop policy if exists "clients_update_own"  on public.clients;
drop policy if exists "clients_delete_own"  on public.clients;

create policy "clients_select_own"
  on public.clients for select
  using (auth.uid() = user_id);

create policy "clients_insert_own"
  on public.clients for insert
  with check (auth.uid() = user_id);

create policy "clients_update_own"
  on public.clients for update
  using      (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "clients_delete_own"
  on public.clients for delete
  using (auth.uid() = user_id);


-- ─── 6. notice_history RLS 정책 ───────────────────────────────
-- 이력은 추가/조회/삭제만 허용. 수정 정책 없음 (immutable 보장).
drop policy if exists "notice_history_select_own"  on public.notice_history;
drop policy if exists "notice_history_insert_own"  on public.notice_history;
drop policy if exists "notice_history_delete_own"  on public.notice_history;

create policy "notice_history_select_own"
  on public.notice_history for select
  using (auth.uid() = user_id);

create policy "notice_history_insert_own"
  on public.notice_history for insert
  with check (auth.uid() = user_id);

create policy "notice_history_delete_own"
  on public.notice_history for delete
  using (auth.uid() = user_id);


-- ─── 7. 검증 쿼리 (실행해서 결과 확인용) ────────────────────────
-- select tablename, rowsecurity from pg_tables
--   where schemaname = 'public' and tablename in ('clients', 'notice_history');
-- → rowsecurity 컬럼이 두 행 모두 't' 여야 함.

-- select policyname, tablename, cmd from pg_policies
--   where schemaname = 'public'
--   order by tablename, policyname;
-- → clients 4개 + notice_history 3개 정책이 보여야 함.
