# AI Agent

점검·조치 이력, 교육 현황, 산업안전 법령정보를 조회하는 읽기 전용 멀티에이전트 서비스입니다.

## 주요 기능

- 점검 및 조치 이력 조회
- 조치 상태, 승인, 반려 현황 조회
- 교육 과정 및 대상자 현황 조회
- 교육 이수율과 미이수 현황 조회
- 산업안전 관련 법령 및 조문 조회
- 최근 대화 문맥을 활용한 연속 질문 처리

## 실행 환경

- Python 3.9 이상
- 실행 중인 백엔드 서버
- OpenAI API 키
- AI 읽기 전용 DB URL
- 국가법령정보 Open API 인증값

백엔드는 사용자 JWT와 회사 정보를 확인하기 위해 필요하며 기본 주소는 `http://127.0.0.1:8000`입니다.

## 설치

Windows PowerShell에서 프로젝트 폴더로 이동한 후 가상환경을 생성합니다.

```powershell
cd ai\aiagent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 환경변수 설정

예제 파일을 복사해 `.env`를 생성합니다.

```powershell
Copy-Item .env.example .env
```

`.env`에 다음 값을 설정합니다.

```env
OPENAI_API_KEY="실제 OpenAI API 키"
OPENAI_MODEL="gpt-4o-mini"
AGENT_READ_DATABASE_URL="팀 공용 AI 읽기 전용 DB URL"
AGENT_READ_DB_SSL_CA="../../backend/ca.pem"
LAW_API_OC="실제 국가법령정보 API 인증값"
```

실제 API 키와 DB 접속 정보는 Git에 커밋하지 않습니다.

그 외 설정은 `.env.example`의 기본값을 사용할 수 있습니다.

## 실행

백엔드가 실행 중인 상태에서 AI 서버를 실행합니다.

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.server:app --reload --port 8001
```

AI 서버는 다음 주소에서 실행됩니다.

```text
http://127.0.0.1:8001
```

서버 상태를 확인합니다.

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
```

정상 응답:

```json
{
  "status": "ok"
}
```

## 멀티에이전트 구조

```text
사용자 질문
    ↓
JWT 인증 및 사용자·회사 확인
    ↓
이전 대화 문맥 불러오기
    ↓
Router Agent
    ├─ 점검·조치 관리 Agent
    ├─ 교육 관리 Agent
    └─ 법령정보 Agent
    ↓
Answer Agent
    ↓
대화 문맥 저장
    ↓
최종 답변
```

### Router Agent

사용자의 질문을 분석해 적절한 전문 Agent로 전달합니다.

### 점검·조치 관리 Agent

AI 전용 읽기 권한으로 다음 정보를 조회합니다.

- 점검 목록과 점검 이력
- 점검 대기, 완료, 조치 필요 현황
- 조치 대기와 조치 완료 현황
- 승인 대기, 승인 완료, 반려 현황
- 담당자, 위치, 카테고리, 위험도 조건
- 점검 이력과 연결된 조치 이력

### 교육 관리 Agent

교육 관련 데이터를 조회합니다.

- 교육 과정과 교육 대상자
- 이수 및 미이수 현황
- 과정별 이수율
- 사용자별 교육 상태
- 카테고리, 교육 유형, 기한 조건
- 교육 대상자 명단

### 법령정보 Agent

국가법령정보 Open API를 이용해 현행 법령을 조회합니다.

지원 법령:

- 산업안전보건법
- 산업안전보건법 시행령
- 중대재해 처벌 등에 관한 법률
- 중대재해 처벌 등에 관한 법률 시행령

지원 기능:

- 특정 조문 조회
- 자연어 기반 관련 조문 검색
- 법률과 시행령 비교
- 이전 질문을 참조한 후속 질문 처리

사내 매뉴얼 데이터는 아직 연결되어 있지 않습니다.

### Answer Agent

전문 Agent가 조회한 결과만 사용해 최종 답변을 생성합니다.

- 답변 생성 온도 `0`
- 조회되지 않은 데이터 생성 금지
- 숫자, 날짜, 상태값을 조회 결과 그대로 사용
- 법령 답변에 근거 조문과 출처 표시

## 대화 기억

AI Agent는 사용자, 회사, 대화 ID를 기준으로 최근 대화 문맥을 기억합니다.

- 최대 기억 범위: 최근 10개 대화
- 새 대화 버튼 사용 시 새로운 대화 ID 생성
- 서버 재시작 시 저장된 대화 문맥 초기화

## 주요 API

### 상태 확인

```http
GET /health
```

### AI 질문

```http
POST /api/agent/query
Authorization: Bearer <JWT>
Content-Type: application/json
```

요청:

```json
{
  "conversation_id": "UUID",
  "user_message": "현재 조치 대기 건수를 알려줘"
}
```

응답:

```json
{
  "final_answer": "현재 조치 대기 건수는 8건입니다.",
  "next_step": "end",
  "context": {},
  "conversation_id": "UUID"
}
```

## 현재 구축 상태

| 기능 | 상태 |
|---|---|
| 점검·조치 관리 Agent | 완료 |
| 교육 관리 Agent | 완료 |
| 법령정보 Agent | 완료 |
| 최근 대화 문맥 처리 | 완료 |
| JWT 사용자·회사 확인 | 완료 |
| 읽기 전용 DB 조회 | 완료 |
| 서버 재시작 이후 대화 보존 | 미지원 |
| DB 데이터 등록 및 수정 | 지원하지 않음 |
