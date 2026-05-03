# 대출/정책자금 안내문 자동 생성기

재무제표 PDF를 업로드하면 핵심 재무 항목을 추출하고, 결과 유형(보증기관 추가 검토 / 정책자금 부결 / 정책자금 승인)을 선택하면 안내문 본문을 자동 작성해주는 Streamlit 앱입니다. Supabase로 사용자 인증 + 고객사 기초정보 + 안내문 생성 이력을 관리합니다.

## 주요 기능

- 🔐 **사용자 로그인** (Supabase Auth, 이메일/비밀번호)
- 📄 **PDF 자동 추출** — 업종, 매출액, 부채총계, 자본총계, 영업이익, 이자비용, 차입금 등을 한국 재무제표에서 자동 파싱
- 📊 **자동 산출** — 부채비율, 이자보상비율, 차입금 총잔액
- 📒 **고객사 관리** — 자주 쓰는 회사를 저장해두고 한 번 클릭으로 폼 채움
- 📜 **이력 저장/조회** — 생성한 안내문을 DB에 보관, 다시 다운로드/삭제 가능
- 🔒 **사용자별 데이터 격리** — Postgres Row-Level Security로 본인 데이터만 조회

## 설치

```bash
pip install -r requirements.txt
```

## Supabase 초기 설정 (1회만)

### 1. 프로젝트 생성
- https://supabase.com → New project → Region 추천 `Northeast Asia (Seoul)`
- DB 비밀번호는 **별도 안전하게 저장**

### 2. API 키 발급
- 좌측 ⚙️ Settings → API Keys
- **Publishable key**(`sb_publishable_...`) 복사 → 아래 `.env`에 입력
- ⚠️ **Secret key는 사용하지 않습니다** (이 앱은 100% 클라이언트 동작, RLS로 보호)

### 3. DB 스키마 적용
- 좌측 SQL Editor → New query
- 프로젝트 폴더의 [`supabase/schema.sql`](supabase/schema.sql) 전체 내용 붙여넣기 → Run
- 검증: `select tablename, rowsecurity from pg_tables where schemaname='public';` 으로 RLS 활성화 확인

### 4. `.env` 파일 작성
프로젝트 루트에 `.env` 파일을 만들고 다음 내용 입력 (`.env.example` 참고):

```
SUPABASE_URL=https://YOURPROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_xxxxxxxxxxxxxxxxx
```

`.gitignore`에 등록되어 있어 git에 커밋되지 않습니다.

## 실행

```bash
streamlit run app.py
```

브라우저가 자동으로 열립니다(기본: http://localhost:8501).

## 사용 흐름

1. **회원가입 → 로그인** (이메일/비밀번호)
2. **재무제표 PDF 업로드** → `PDF에서 값 추출` 클릭
3. **추출값 확인 및 수정** — 단위, 업종, 매출액, 부채/자본/영업이익/이자비용/차입금 등을 확인하고 필요 시 수정
4. **(선택) 사이드바**에서 자주 쓰는 회사를 저장하거나, 저장된 회사를 선택해 폼 자동 채움
5. **결과 유형 선택** — 보증기관 추가 검토 / 정책자금 부결 / 정책자금 승인
6. **안내문 생성** → 텍스트 다운로드 또는 [이력에 저장] 버튼으로 DB 보관
7. **이력 조회 탭**에서 과거 안내문 다시 보기/다운로드/삭제

## 자동 산출 지표

- 부채비율 = 부채총계 / 자본총계 × 100
- 이자보상비율 = 영업이익 / 이자비용 (영업적자 시 "영업적자"로 표기)
- 차입금 총잔액 = 단기차입금 + 장기차입금

## 파일 구성

| 파일 | 역할 |
|------|------|
| `app.py` | Streamlit UI (인증 게이팅, 사이드바 고객사, 메인 탭) |
| `auth.py` | Supabase Auth 흐름 (로그인/회원가입/로그아웃, 세션 복원) |
| `db.py` | Supabase 테이블 CRUD (clients, notice_history) |
| `supabase_client.py` | 세션별 Supabase 클라이언트 싱글턴 + 환경변수 lazy 검증 |
| `pdf_parser.py` | pdfplumber + 정규식 기반 한국 재무제표 파싱 |
| `templates.py` | 안내문 3종 템플릿 + 부결 사유/전략 기본값 |
| `supabase/schema.sql` | DB 스키마 + RLS 정책 (멱등) |
| `test_app.py` | 회귀 테스트 (55개) |
| `.env.example` | 환경변수 템플릿 |

## 보안

- **RLS 활성화**: 사용자가 자기 데이터만 조회/수정/삭제 가능 (Postgres 레벨)
- **Secret key 미사용**: 앱은 publishable key만 사용. RLS가 클라이언트 키 노출 위험을 흡수
- **PDF 자원 한도**: 10MB / 100페이지 (DoS 방지)
- **PDF 원문 truncate**: 추출 후 1KB만 보관, 세션 초기화 버튼 제공
- **`.env` 보호**: `.gitignore` 등록 + `.env.example` 템플릿 분리

## 테스트

```bash
python -m unittest test_app -v
```

55개 회귀 테스트가 PDF 파싱, 단위 환산, 템플릿 렌더, 영업적자 처리, 파일명 sanitize, 환경변수 검증, DB 화이트리스트를 커버합니다.

## 주의

- 재무제표 양식이 회사/기관마다 달라 PDF 자동 추출이 항상 성공하지는 않습니다. 추출 실패 항목은 화면에서 직접 입력하세요.
- 안내문에 들어갈 금액은 PDF 단위 설정에 따라 자동 환산됩니다(억원/만원/원 단위로 출력).
- 외부 호스팅 시에는 Streamlit Auth 추가 + HTTPS + XSRF 보호 등 추가 작업 필요. 현재는 로컬 또는 신뢰된 LAN 사용 가정.
