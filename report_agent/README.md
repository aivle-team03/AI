# BOSS 안전 보고서 생성 API

`report_agent`는 BOSS Backend에서 전달받은 안전·점검·조치 데이터를 바탕으로 안전 관리 문서를 생성하는 FastAPI 서비스입니다. OpenAI와 LangGraph로 데이터를 정리·검토하고, 제공된 Word 양식에 맞춘 DOCX 문서를 생성한 뒤 S3에 업로드합니다.

## 보고서 종류

- 위험성평가표
- 위험성평가 보고서
- 경영책임자 검토지시서
- 종사자에 의한 유해위험요인 보고서
  
## 주요 기능

- 위험성평가표 생성 및 데이터 보정·검토
- 위험성평가보고서 생성
- 경영책임자 검토지시서 생성
- 종사자 의견 기반 개선 보고서 생성
- 생성된 DOCX의 S3 업로드 경로 반환
- 매일 자정에 전일 데이터를 이용해 위험성평가표를 자동 생성하는 스케줄러

## 보고서 생성 

1. 위험성평가표
- 점검 이력/ 조치 이력을 기반으로 관련 보고서를 생성
- 날짜 별로 위험성 평가표 생성

2. 종사자에 의한 유해위험요인 보고서
- 신고 게시판 이력 기반 보고서를 생성
- 각 항목 별 최초 1회만 생성

3. 위험성평가 보고서/경영책임자 검토지시서
- 위험성 평가표를 기반으로 관련 보고서를 생성성
- 안전관리자가 지정한 기간 별로 보고서 생성

## 문서 생성 흐름

```text
Backend 안전 데이터
  → 데이터 집계 및 LLM 분석
  → 보정·검토 단계
  → DOCX 양식 채우기
  → S3 업로드
  → 생성 결과 및 파일 경로 응답
```

원본 업무 데이터의 조회·저장·권한 관리는 Backend가 담당합니다. 이 서비스는 전달받은 데이터를 보고서 형식으로 정리하고, 생성 결과를 제공하는 역할에 집중합니다.

## 멀티에이전트 구조

1. 위험성평가표/종사자에 의한 유해위험요인 보고서

```
점검/조치 이력
    ↓
컬럼 선별 및 점검·조치 데이터 매핑
    ↓
데이터 전처리 Agent
    ↓
데이터 검토 Agent
    ├─ 검토 실패 → 데이터 전처리 Agent 재시도
    └─ 통과
         ↓
보고서 양식 대입 노드
    ↓
보고서 생성
    ├─ 위험성평가표.docx
    └─ 종사자에 의한 유해위험요인 보고서.docx
```

2. 위험성평가 보고서/경영책임자 검토지시서

```
위험성평가표
    ↓
집계 노드
    ↓
데이터 분석 Agent
    ↓
보고서 작성 Agent
    ↓
보고서 검토 Agent
    ├─ 검토 실패 → 보고서 작성 Agent 재시도
    └─ 통과
    ↓
보고서 양식 대입 노드
    ↓
보고서 생성
    ├─ 위험성평가 보고서.docx
    └─ 경영책임자 검토지시서.docx
```

## API

서버 실행 후 Swagger UI에서 요청·응답 스키마와 예시를 확인할 수 있습니다.

- Swagger UI: `http://127.0.0.1:8004/docs`
- 상태 확인: `GET /health`

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `POST` | `/api/report/risk-assessment/form/generate` | 위험성평가표를 생성하고 일별 산출물을 저장합니다. |
| `POST` | `/api/report/risk-assessment/report/generate` | 위험성평가보고서 DOCX를 생성합니다. |
| `POST` | `/api/report/management-review-order/generate` | 경영책임자 검토지시서 DOCX를 생성합니다. |
| `POST` | `/api/report/worker-feedback/generate` | 종사자 의견 기반 개선 보고서 DOCX를 생성합니다. |

보고서 요청은 회사, 사용자, CCTV, 이벤트, 점검, 조치 이력 등 Backend에서 수집한 데이터를 JSON으로 전달받습니다. 위험성평가표 요청에는 `final_history_rows`를, 종사자 의견 보고서 요청에는 `worker_feedback_rows`를 함께 전달합니다. 정확한 필수·선택 필드는 Swagger UI를 기준으로 사용하세요.

## 로컬 실행

Python 3.10 이상 환경을 권장합니다.

```powershell
cd report_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --reload --reload-dir app --port 8004
```

정상적으로 실행되면 다음 요청으로 확인할 수 있습니다.

```powershell
Invoke-RestMethod http://127.0.0.1:8004/health
```

응답 예시:

```json
{"status":"ok"}
```

## 환경 변수

프로젝트 루트가 아닌 `report_agent/.env` 파일을 읽습니다. 비밀값은 Git에 커밋하지 마세요.

```env
OPENAI_API_KEY=""
OPENAI_MODEL="gpt-4.1-mini"
MAX_RETRY_COUNT="2"

# 일일 위험성평가표 자동 생성 설정
DAILY_REPORT_SCHEDULER_ENABLED="true"
DAILY_REPORT_TIMEZONE="Asia/Seoul"
RISK_FORM_CORRECTION_BATCH_SIZE="10"
RISK_FORM_TIMEOUT_SECONDS="1200"
```

S3 업로드는 AWS 자격 증명 체인(예: IAM Role, AWS CLI 프로필 또는 환경 변수)을 사용합니다. 현재 업로드 버킷은 코드의 `app/common/s3_upload.py`에서 관리합니다.

## 자동 생성 스케줄러

API가 시작되면 스케줄러가 함께 시작됩니다. 기본 설정에서는 `Asia/Seoul` 기준 매일 `00:00:05`에 전일 데이터를 이용해 위험성평가표를 생성합니다. 로컬 개발에서 자동 실행이 필요 없다면 아래처럼 비활성화하세요.

```env
DAILY_REPORT_SCHEDULER_ENABLED="false"
```

## 디렉터리 구성

```text
report_agent/
├─ app/
│  ├─ main.py                         # FastAPI 엔트리포인트
│  ├─ risk_assessment_form_graph/     # 위험성평가표 생성 그래프
│  ├─ risk_assessment/                # 위험성평가보고서 생성 그래프
│  ├─ management/                     # 경영책임자 검토지시서 생성 그래프
│  ├─ worker_feedback/                # 종사자 의견 개선 보고서 생성 그래프
│  ├─ common/                         # Backend 데이터·S3 업로드 유틸리티
│  └─ daily_report_scheduler.py       # 일일 자동 생성 작업
├─ report_template/                   # DOCX 보고서 양식
├─ scripts/                           # 문서 작성·데이터 변환 스크립트
├─ requirements.txt
└─ README.md
```

생성 과정에서 만들어지는 로컬 결과물은 `output/` 아래에 저장되며 Git에서 제외됩니다.
