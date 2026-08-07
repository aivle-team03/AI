# Video Agent

Google Veo 기반 안전 교육 영상 생성 에이전트.

교육 문서(PDF/PPTX/TXT) 또는 텍스트를 입력받아 장면별 대본과 영상을 생성하고, 품질을 검수한 뒤 Cloudinary에 업로드한다.

## 파이프라인

```
문서 파싱 → 문서 분석 → 학습 목표 추출 → 스토리보드 생성
  → Veo 8초 클립 병렬 생성 (최대 4개 동시)
  → FFmpeg 병합
  → 품질 검수 (대본-음성 일치도 / 화면 텍스트 검사)
  → Cloudinary 업로드
```

작업 상태는 Redis에 저장되며 TTL은 24시간이다.

## 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # 값 채우기
```

Redis가 떠 있어야 한다.

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

### 서버로 실행

영상 생성은 Celery 워커가 처리하므로 **API 서버와 워커를 모두** 띄워야 한다.

```bash
uvicorn app.server:app --port 8100
```

```bash
celery -A app.celery_app worker --loglevel=info --pool=solo
```

> Windows에서는 기본 prefork 풀이 동작하지 않으므로 `--pool=solo`가 필요하다.
> 워커를 띄우지 않으면 요청은 `202`를 반환하지만 상태가 `PENDING`에서 진행되지 않는다.
>
> 워커는 API 서버와 다른 프로세스다. 업로드 원본은 OS 임시 디렉터리에 두므로 두 프로세스가
> **같은 머신**에 있어야 한다. 별도 컨테이너로 띄운다면 임시 디렉터리를 공유 볼륨으로 마운트할 것.

| Method | Endpoint | 설명 |
| :--- | :--- | :--- |
| `POST` | `/video/generate` | 생성 시작. `task_id` 반환 (202) |
| `GET` | `/video/generate/{task_id}/status` | 진행 상태 및 결과 조회 |
| `GET` | `/health` | 헬스 체크 |

`POST /video/generate` 는 `multipart/form-data` 로 받는다.

| 필드 | 필수 | 설명 |
| :--- | :---: | :--- |
| `company_id` | ✅ | 요청 회사 ID |
| `file` | △ | 교육 문서 (PDF/PPTX/TXT) |
| `text_content` | △ | 문서 대신 넣을 텍스트 |
| `title`, `category`, `type` | | 메타데이터. 상태 응답에 그대로 실려 나간다 |
| `request` | | 영상 제작 요청사항 |

`file` 과 `text_content` 중 하나는 반드시 있어야 한다.

### 단독 실행 (서버 없이)

```bash
python agent_main.py ./sample.pdf --company-id 1 --pretty
```

## 백엔드와의 관계

이 에이전트는 **영상 생성만** 담당한다. 인증, `company_id` 판별, `Education` 테이블 적재는 백엔드 책임이다.

- 이 서비스는 DB에 쓰지 않는다. `company_id` 는 호출자가 넘긴 값을 상태에 기록만 한다.
- 이 서비스는 인증하지 않는다. **외부에 직접 노출하지 말 것.** 백엔드 뒤에 두거나 내부 네트워크에서만 접근 가능해야 한다.
- 완료 결과는 백엔드가 `status` 를 폴링해 가져간다.

## 현재 상태

백엔드(`aivle-team03/backend`)의 `app/services/ai/` 및 `app/services/veo_service.py` 에서 이관한 코드다.
백엔드는 이 서비스를 호출하는 프록시로 전환되어, 인증과 `company_id` 판별, `Education` 테이블
영속화만 담당한다.

이관 시 백엔드와 달라진 점:

- `Education` 테이블 직접 INSERT 제거. 백엔드가 상태를 폴링해 저장한다
- 산출물 경로 `static/` → `output/` (`OUTPUT_DIR` 로 설정 가능)
- 업로드 원본을 영구 경로가 아닌 OS 임시 디렉터리에 저장하고 `finally` 에서 삭제.
  실패하거나 조기 반환해도 디스크에 남지 않는다.
- 실행 방식은 backend와 동일하게 Celery 워커를 쓴다
