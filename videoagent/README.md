# Video Agent

Google Veo 기반 안전 교육 영상 생성 에이전트.

교육 문서(PDF/PPTX/TXT) 또는 텍스트를 입력받아 장면별 대본과 영상을 생성하고, 품질을 검수한 뒤 S3에 업로드한다.

영상은 한국어로 만들고, **같은 클립에 번역·TTS 를 얹은 영어 더빙판을 함께 생성**한다.

## 파이프라인

```
문서 파싱 → 문서 분석 → 학습 목표 추출 → 스토리보드 생성
  → Veo 클립 병렬 생성 (4/6/8초, 최대 4개 동시)
  → FFmpeg 병합
  → 품질 검수 (시각 QA / 대본-음성 일치도)
  → 더빙: 대본 번역 → TTS → 클립별 오디오 교체 → 병합
  → S3 업로드 (한국어 / 영어 2개)
```

### 더빙을 쓰는 이유

Veo 로 언어판을 따로 뽑으면 **클립 비용이 그대로 두 배**가 된다. 영상 트랙은 언어와
무관하므로 한국어 클립을 그대로 쓰고 오디오만 갈아끼운다. 화면이 같아 시각 검수도
다시 할 필요가 없고, TTS 는 준 대로 말하므로 오디오 검수도 불필요하다.

번역은 클립 길이(4/6/8초)에 맞는 목표 글자 수를 장면마다 지시해 받는다. 넘치면
TTS 속도를 한 번 올려 맞추고, 짧으면 무음으로 채운다. 결과 길이는 원본과 같으므로
시청 진도(`last_position_seconds`)가 두 언어에서 같은 장면을 가리킨다.

더빙 실패는 한국어판 저장을 막지 않는다. `video_url_en` 이 비어 있을 뿐이다.

작업 상태는 Redis에 저장되며 TTL은 24시간이다.

## 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # 값 채우기
```

Google Cloud 자격 증명이 필요하다. Veo(Vertex AI)와 TTS 가 같은 서비스 계정 키를 쓴다.

```
GOOGLE_APPLICATION_CREDENTIALS=/절대경로/video_create.json
```

환경변수가 없으면 Veo 는 작업 디렉터리의 `video_create.json` 으로 폴백하지만
**TTS 는 폴백이 없다.** 값이 비면 더빙만 조용히 실패한다.

GCP 프로젝트에서 **Cloud Text-to-Speech API 를 활성화**해야 한다.

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
| `GET` | `/video/generate/{task_id}/status` | 진행 상태 및 결과 조회 (`video_url`, `video_url_en`) |
| `GET` | `/health` | 헬스 체크 |

`POST /video/generate` 는 `multipart/form-data` 로 받는다.

| 필드 | 필수 | 설명 |
| :--- | :---: | :--- |
| `company_id` | ✅ | 요청 회사 ID |
| `file` | △ | 교육 문서 (PDF/PPTX/TXT) |
| `text_content` | △ | 문서 대신 넣을 텍스트 |
| `title`, `category`, `type` | | 메타데이터. 상태 응답에 그대로 실려 나간다 |
| `request` | | 영상 제작 요청사항 |

`file` 과 `text_content` 중 하나는 반드시 있어야 한다. 발화 언어를 고르는 필드는 없다.
항상 한국어로 만들고 영어 더빙판을 함께 낸다.

상태 응답의 영상 필드는 두 개다.

| 필드 | 설명 |
| :--- | :--- |
| `video_url` | 한국어 영상 (Veo 네이티브 오디오) |
| `video_url_en` | 영어 더빙판. 더빙에 실패하면 `null` |

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
- 산출물 저장소는 Cloudinary가 아니라 S3다 (`AWS_S3_MEDIA_BUCKET`, `MEDIA_BASE_URL`)

### 더빙 도입 이후 유의점

- TTS 클라이언트는 `transport="rest"` 로 고정한다. 기본값인 gRPC 는 Celery prefork
  워커에서 fork 이후 데드락에 빠져 예외도 로그도 없이 멈춘 사례가 있다.
- ffmpeg 호출에는 `-nostdin` 과 `timeout` 을 반드시 준다. 워커 환경에서 stdin 이
  닫히지 않으면 출력 파일 없이 `-i` 만 줘도 대기한다.
- 오디오 길이를 맞출 때 `apad` 는 무한히 패딩하므로 `-t` 로 끊는다. `-shortest` 는
  `filter_complex` 출력에 걸리지 않아 무한 루프가 된다.
- `_SCRIPT_LENGTH_TO_CLIP_SECONDS["en"]` 는 초당 12자로 잡은 **추정값**이다.
  한국어처럼 실측으로 보정할 것. 어긋나면 대사가 잘리거나 뒤가 빈다.
