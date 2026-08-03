# BP3 AI Agent

FastAPI와 LangGraph로 구성된 BP3 AI 서비스입니다. 점검·조치 관리 agent는
백엔드가 검증한 사용자 범위를 사용해 조회 전용 DB view에 직접 접근합니다.

## Environment

`.env.example`을 기준으로 OpenAI, 백엔드, 읽기 전용 DB 연결을 설정합니다.
`AGENT_READ_DATABASE_URL`은 아래 마이그레이션의 8개 view에만 SELECT 가능한
별도 계정을 사용해야 합니다.

- `migrations/20260803_agent_inspection_action_read_scope.sql`: 점검·조치 5개 view
- `migrations/20260803_agent_education_read_scope.sql`: 교육 3개 view

## Run

```bash
python3 -m uvicorn app.server:app --reload --port 8001
```

## Request

```http
POST /api/agent/query
Authorization: Bearer <backend-access-token>
Content-Type: application/json

{"user_message":"이번 주 조치 대기 내역을 알려줘"}
```

`company_id`와 역할은 요청 본문에서 받지 않습니다. AI 서비스는 JWT를 기존
`GET /api/users/me`에 전달해 검증하고, 응답의 관리자 회사 범위만 직접 조회합니다.
