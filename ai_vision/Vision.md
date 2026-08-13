# BOSS AI CCTV 서비스

## 1차 통합 구조

`ai_server.py`는 테스트 영상을 직접 분석해 프론트에는 바운딩 박스가 그려진
MJPEG 스트림을 제공하고, 위험 감지 때는 스냅샷 URL을 포함해 백엔드 이벤트 API에
저장 요청을 보냅니다.

```text
AI 테스트 영상/모델 → ai_server:8002 → 프론트 분석 스트림
                                 └→ backend /api/ai/events → DB 이벤트 이력
```

## 실행

백엔드와 프론트를 실행한 뒤 `AI/ai_vision` 폴더에서 다음을 실행합니다.

```powershell
pip install -r requirements.txt
python -m uvicorn ai_server:app --host 127.0.0.1 --port 8002
```

- 상태 확인: `http://127.0.0.1:8002/health`
- 화재 분석 스트림: `http://127.0.0.1:8002/streams/fire-01`
- 지게차 분석 스트림: `http://127.0.0.1:8002/streams/forklift-03`

테스트 입력은 `test3.mp4`(화재), `test1.mp4`(지게차)이며 `AI/ai_vision` 폴더에 둡니다.
프론트에는 원본 MP4를 복사하지 않습니다.

## 현재 설정 주의사항

AI 이벤트 전송 주소는 기본 `http://127.0.0.1:8000/api/ai/events`입니다. 다른
환경에서는 `AI_BACKEND_URL`과 `AI_PUBLIC_URL` 환경 변수를 설정합니다. 현재
`cctv_id`와 `category_id`는 화재 `1/1`, 지게차 `2/1000006`을 사용합니다.
DB의 실제 카테고리 ID가 다르면 `ai_server.py`의 `CAMERAS` 값을 맞춰야 합니다.
같은 테스트 영상을 재시작해서 이벤트가 반복 저장되는 것을 막기 위해, 카메라별
DB 저장은 기본 300초 쿨다운을 적용합니다. 필요하면 `AI_EVENT_COOLDOWN_SECONDS`
환경 변수로 조절할 수 있습니다.
## EC2 deployment

When `ai_vision` runs on a separate GPU EC2, add these values to
`AI/ai_vision/.env` on that instance. Use the CPU EC2 private IP or private
DNS; do not use its public IP. `ai_verify` also reads this same `.env` file.

```env
AI_BACKEND_URL=http://<cpu-ec2-private-ip-or-dns>:8000
AI_PUBLIC_URL=https://<public-app-domain>/vision
```

Run the vision service so the CPU EC2 reverse proxy can reach it:

```bash
python -m uvicorn ai_server:app --host 0.0.0.0 --port 8002
```

Allow port 8002 on the GPU EC2 only from the CPU EC2 security group. Browsers
should use the `/vision` proxy path, not the GPU EC2 address.
