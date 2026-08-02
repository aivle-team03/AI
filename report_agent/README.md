# Warehouse Safety AI Report API

세 가지 안전 보고서 생성을 위한 FastAPI 애플리케이션입니다.

## 보고서 유형

- 본사 보고용 종합 데이터 분석 보고서: 추세, KPI, 주요 위험 구역, 조치/승인/교육 현황
- 현장관리자 확인용 보고서: 이상패턴 분석 및 개선권고안
- 보관 및 증빙용 보고서: 안전관리 원본 데이터 정리

## 실행

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

Swagger: http://127.0.0.1:8001/docs

`.env`에 `OPENAI_API_KEY`를 설정하세요.

## API

- GET `/health`: 서버 상태 확인
- POST `/api/reports/headquarters/generate`: 본사 보고용 추세/KPI 종합 데이터 분석 보고서
- POST `/api/reports/site-anomaly/generate`: 현장관리자 확인용 이상패턴/개선권고안 보고서
- POST `/api/reports/evidence-content`: 보관 및 증빙용 안전관리 데이터 정리 보고서

샘플 요청은 `sample_request.json`을 사용하세요.
