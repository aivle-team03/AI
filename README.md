# BP3 AI Agent

FastAPI와 LangGraph로 구성된 BP3 AI 서비스입니다. 점검·조치 관리 agent는
DB에 직접 접속하지 않고 백엔드의 관리자 전용 read-only API를 호출합니다.

## Environment

`.env.sample`을 기준으로 `OPENAI_API_KEY`, `BACKEND_API_URL`을 설정합니다.
백엔드에는 별도 `AGENT_READ_DATABASE_URL`과
`migrations/20260803_agent_inspection_action_read_scope.sql`의 DB view가 필요합니다.

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

`company_id`와 역할은 요청 본문에서 받지 않습니다. AI 서비스가 전달한 JWT를
백엔드가 검증하고, 확인된 관리자의 회사 범위만 조회합니다.
