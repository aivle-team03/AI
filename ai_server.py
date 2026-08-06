"""BOSS CCTV AI 데모 서버.

실행: python -m uvicorn ai_server:app --host 127.0.0.1 --port 8001

테스트 영상은 이 AI 서비스가 소유하고, 프론트에는 분석 결과만 MJPEG로
제공한다. 위험 감지 시에는 캡처 URL과 함께 백엔드 이벤트 API에도 저장한다.
"""

from __future__ import annotations

import os
import asyncio
import threading
import time
import json
from uuid import uuid4
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from ultralytics import YOLO


BASE_DIR = Path(__file__).resolve().parent
SNAPSHOT_DIR = BASE_DIR / "snapshots"
EVENT_STATE_PATH = SNAPSHOT_DIR / "event_cooldowns.json"
BACKEND_URL = os.getenv("AI_BACKEND_URL", "http://127.0.0.1:8000")
PUBLIC_URL = os.getenv("AI_PUBLIC_URL", "http://127.0.0.1:8001")
EVENT_COOLDOWN_SECONDS = int(os.getenv("AI_EVENT_COOLDOWN_SECONDS", "300"))
# 💡 소화장비 자동 점검 주기 (기본 7200초 = 2시간 / 테스트 시 짧게 변경 가능)
INSPECTION_INTERVAL_SECONDS = int(os.getenv("AI_INSPECTION_INTERVAL_SECONDS", "7200"))


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    source: Path
    model_path: Path
    category_name: str
    detector: str
    cctv_id: int
    category_id: int
    confidence: float = 0.4
    sample_fps: float = 1.0


CAMERAS = {
    "fire-01": CameraConfig(
        "fire-01", BASE_DIR / "test3.mp4", BASE_DIR / "fire_finetuned_v5.pt",
        "화재 감지", "fire", 1, 1, sample_fps=10.0,
    ),
    "forklift-03": CameraConfig(
        "forklift-03", BASE_DIR / "test1.mp4", BASE_DIR / "person-forklift2-best.pt",
        "지게차 접근 위험", "forklift", 2, 1000006, sample_fps=10.0,
    ),
    # 💡 소화기/소화전 점검용 카메라 추가
    "extinguisher-01": CameraConfig(
        "extinguisher-01", BASE_DIR / "test3.mp4", BASE_DIR / "extinguisher_best.pt",
        "소화장비 미감지", "extinguisher", 3, 1000008, sample_fps=1.0,
    ),
}

app = FastAPI(title="BOSS AI CCTV service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_models: dict[Path, YOLO] = {}
_model_lock = threading.Lock()
_events: deque[dict[str, Any]] = deque(maxlen=200)
_event_lock = threading.Lock()
_next_event_id = 1
_last_persisted_events: dict[str, float] = {}


def _load_event_cooldowns() -> None:
    if not EVENT_STATE_PATH.is_file():
        return
    try:
        _last_persisted_events.update(json.loads(EVENT_STATE_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return


def _save_event_cooldowns() -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    EVENT_STATE_PATH.write_text(json.dumps(_last_persisted_events), encoding="utf-8")


def should_persist_event(camera_id: str) -> bool:
    now = time.time()
    last_persisted_at = _last_persisted_events.get(camera_id, 0)
    if now - last_persisted_at < EVENT_COOLDOWN_SECONDS:
        return False
    _last_persisted_events[camera_id] = now
    _save_event_cooldowns()
    return True


def get_model(model_path: Path) -> YOLO:
    with _model_lock:
        if model_path not in _models:
            if not model_path.is_file():
                raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {model_path}")
            _models[model_path] = YOLO(str(model_path))
            print(f"모델 로드: {model_path.name}", flush=True)
        return _models[model_path]


def send_backend_event(config: CameraConfig, snapshot_url: str) -> None:
    """백엔드 POST /api/ai/events API 호출하여 이벤트 적재"""
    payload = (
        '{"cctv_id": %d, "category_id": %d, "image_url": "%s"}'
        % (config.cctv_id, config.category_id, snapshot_url)
    ).encode("utf-8")
    request = Request(
        f"{BACKEND_URL}/api/ai/events", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            print(f"백엔드 이벤트 저장 완료: {config.camera_id} ({response.status})", flush=True)
    except (URLError, TimeoutError) as error:
        print(f"백엔드 이벤트 저장 실패 [{config.camera_id}]: {error}", flush=True)


def publish_event(config: CameraConfig, confidence: float, source_time: float, snapshot: bytes) -> None:
    global _next_event_id
    with _event_lock:
        event_id = _next_event_id
        _next_event_id += 1
        snapshot_id = uuid4().hex
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        (SNAPSHOT_DIR / f"{snapshot_id}.jpg").write_bytes(snapshot)
        snapshot_url = f"{PUBLIC_URL}/snapshots/{snapshot_id}"
        _events.append({
            "id": event_id,
            "cameraId": config.camera_id,
            "categoryName": config.category_name,
            "confidence": round(confidence, 3),
            "sourceTime": round(source_time, 2),
            "detectedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "snapshotUrl": snapshot_url,
        })
    if should_persist_event(config.camera_id):
        threading.Thread(
            target=send_backend_event, args=(config, snapshot_url), daemon=True,
        ).start()
    else:
        print(f"DB 이벤트 중복 저장 생략: {config.camera_id} ({EVENT_COOLDOWN_SECONDS}초 쿨다운)", flush=True)


def _boxes_by_class(result: Any) -> tuple[list[tuple[tuple[int, int, int, int], float]], list[tuple[tuple[int, int, int, int], float]]]:
    forklifts: list[tuple[tuple[int, int, int, int], float]] = []
    persons: list[tuple[tuple[int, int, int, int], float]] = []
    if result.boxes is None:
        return forklifts, persons
    for box in result.boxes:
        class_id = int(box.cls[0])
        coordinates = tuple(map(int, box.xyxy[0].tolist()))
        confidence = float(box.conf[0])
        if class_id == 0:
            forklifts.append((coordinates, confidence))
        elif class_id == 1:
            persons.append((coordinates, confidence))
    return forklifts, persons


def _center(box: tuple[int, int, int, int]) -> tuple[int, int]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def annotate_fire(frame: Any, result: Any) -> tuple[Any, bool]:
    annotated = frame.copy()
    hazard = result.boxes is not None and len(result.boxes) > 0
    if result.boxes is not None:
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            confidence = float(box.conf[0])
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (20, 40, 235), 2, cv2.LINE_AA)
            cv2.putText(annotated, f"FIRE {confidence:.0%}", (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 40, 235), 2, cv2.LINE_AA)
    cv2.putText(annotated, "FIRE MONITORING", (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return annotated, hazard


def annotate_forklift(frame: Any, result: Any) -> tuple[Any, bool]:
    annotated = frame.copy()
    forklifts, persons = _boxes_by_class(result)
    danger = False
    for forklift_box, forklift_confidence in forklifts:
        forklift_center = _center(forklift_box)
        cv2.circle(annotated, forklift_center, 6, (255, 130, 0), -1, cv2.LINE_AA)
        cv2.putText(annotated, f"FORKLIFT {forklift_confidence:.0%}", (forklift_center[0] + 8, forklift_center[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 130, 0), 2, cv2.LINE_AA)
    for person_box, person_confidence in persons:
        person_center = _center(person_box)
        if not forklifts:
            cv2.circle(annotated, person_center, 6, (0, 210, 100), -1, cv2.LINE_AA)
            cv2.putText(annotated, f"PERSON {person_confidence:.0%}", (person_center[0] + 8, person_center[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 210, 100), 2, cv2.LINE_AA)
            continue
        forklift_box, _ = min(forklifts, key=lambda item: (person_center[0] - _center(item[0])[0]) ** 2 + (person_center[1] - _center(item[0])[1]) ** 2)
        forklift_center = _center(forklift_box)
        distance = ((person_center[0] - forklift_center[0]) ** 2 + (person_center[1] - forklift_center[1]) ** 2) ** 0.5
        if distance <= 60:
            color, status = (20, 40, 235), "DANGER"
            danger = True
        elif distance <= 120:
            color, status = (0, 165, 255), "WARNING"
        else:
            color, status = (0, 210, 100), "SAFE"
        cv2.circle(annotated, person_center, 6, color, -1, cv2.LINE_AA)
        cv2.line(annotated, person_center, forklift_center, color, 2, cv2.LINE_AA)
        label_position = ((person_center[0] + forklift_center[0]) // 2, (person_center[1] + forklift_center[1]) // 2 - 8)
        cv2.putText(annotated, f"{distance:.0f}px  {status}", label_position, cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
        cv2.putText(annotated, f"PERSON {person_confidence:.0%}", (person_center[0] + 8, person_center[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)
    cv2.putText(annotated, f"FORKLIFT {len(forklifts)}  |  PERSON {len(persons)}", (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return annotated, danger


@dataclass
class CameraWorker:
    config: CameraConfig
    latest_jpeg: bytes | None = None
    frame_version: int = 0
    running: bool = False
    thread: threading.Thread | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    reset_requested: bool = True
    reset_complete: threading.Event = field(default_factory=threading.Event)
    consecutive_hits: int = 0
    emitted_in_session: bool = False

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, name=f"ai-{self.config.camera_id}", daemon=True)
        self.thread.start()

    def reset(self) -> None:
        with self.lock:
            self.consecutive_hits = 0
            self.emitted_in_session = False
            self.reset_requested = True
            self.reset_complete.clear()
        self.start()

    def _run(self) -> None:
        capture = cv2.VideoCapture(str(self.config.source))
        if not capture.isOpened():
            raise RuntimeError(f"테스트 영상을 열 수 없습니다: {self.config.source}")
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        initial_ok, initial_frame = capture.read()
        if initial_ok:
            ok, encoded = cv2.imencode(".jpg", initial_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with self.lock:
                    self.latest_jpeg = encoded.tobytes()
                    self.frame_version += 1
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        model = get_model(self.config.model_path)
        frame_step = max(1, round(fps / self.config.sample_fps))
        frame_index = 0
        while self.running:
            with self.lock:
                if self.reset_requested:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    frame_index = 0
                    self.consecutive_hits = 0
                    self.emitted_in_session = False
                    self.reset_requested = False
                    self.reset_complete.set()
            started_at = time.perf_counter()
            frame = None
            for _ in range(frame_step):
                ok, candidate = capture.read()
                if not ok:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    frame_index = 0
                    ok, candidate = capture.read()
                if ok:
                    frame, frame_index = candidate, frame_index + 1
            if frame is None:
                continue
            result = model.predict(source=frame, conf=self.config.confidence, verbose=False)[0]
            if self.config.detector == "forklift":
                annotated, hazard = annotate_forklift(frame, result)
            else:
                annotated, hazard = annotate_fire(frame, result)
            ok, encoded = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 65])
            jpeg = encoded.tobytes() if ok else b""
            self.consecutive_hits = self.consecutive_hits + 1 if hazard else 0
            if self.consecutive_hits >= 3 and not self.emitted_in_session:
                self.emitted_in_session = True
                confidence = float(result.boxes.conf.max()) if result.boxes is not None else 0.0
                publish_event(self.config, confidence, frame_index / fps, jpeg)
            if jpeg:
                with self.lock:
                    self.latest_jpeg = jpeg
                    self.frame_version += 1
            time.sleep(max(0, 1 / self.config.sample_fps - (time.perf_counter() - started_at)))
        capture.release()


workers = {camera_id: CameraWorker(config) for camera_id, config in CAMERAS.items()}
_load_event_cooldowns()


# 💡 [신규 추가] 2시간 주기 소화장비 점검 백그라운드 스케줄러
def _run_equipment_inspector() -> None:
    time.sleep(5)  # 서버 구동 후 첫 5초 대기
    while True:
        print(f"\n🔍 [자동 점검] 소화장비(소화기/소화전) 존재 여부 검사를 시작합니다...", flush=True)
        for camera_id, config in CAMERAS.items():
            if config.detector != "extinguisher":
                continue

            worker = workers.get(camera_id)
            if not worker:
                continue

            worker.start()
            time.sleep(1)

            with worker.lock:
                jpeg = worker.latest_jpeg

            if not jpeg:
                print(f"⚠️ [{camera_id}] 최신 프레임을 불러오지 못했습니다.", flush=True)
                continue

            nparr = np.frombuffer(jpeg, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            model = get_model(config.model_path)

            result = model.predict(source=frame, conf=config.confidence, verbose=False)[0]
            detected_count = len(result.boxes) if result.boxes is not None else 0

            # 💡 소화기/소화전이 0개 탐지되면 이벤트 발행 및 DB 저장
            if detected_count == 0:
                print(f"🚨 [소화장비 미감지 경고] {camera_id}: 소화기/소화전이 탐지되지 않았습니다! 이벤트 전송 중...", flush=True)
                publish_event(config, confidence=0.0, source_time=time.time(), snapshot=jpeg)
            else:
                max_conf = float(result.boxes.conf.max())
                print(f"✅ [소화장비 정상] {camera_id}: {detected_count}개 탐지됨 (신뢰도: {max_conf:.0%})", flush=True)

        time.sleep(INSPECTION_INTERVAL_SECONDS)


@app.on_event("startup")
def preload_models() -> None:
    """Warm model runtime at startup; CCTV video inference still starts per stream request."""
    unique_model_paths = {config.model_path for config in CAMERAS.values()}
    for model_path in unique_model_paths:
        model = get_model(model_path)
        model.predict(source=np.zeros((640, 640, 3), dtype=np.uint8), verbose=False)
        print(f"AI 모델 워밍업 완료: {model_path.name}", flush=True)
    
    # 💡 2시간 주기 소화장비 점검 스케줄러 스레드 자동 가동
    threading.Thread(target=_run_equipment_inspector, name="ai-extinguisher-inspector", daemon=True).start()
    print(f"소화장비 자동 점검 스케줄러 가동 완료 (주기: {INSPECTION_INTERVAL_SECONDS}초)", flush=True)
    print("AI 모델 사전 로드 완료. CCTV 스트림 요청을 기다립니다.", flush=True)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "cameras": list(CAMERAS), "backendUrl": BACKEND_URL}


@app.get("/streams/{camera_id}")
async def stream(camera_id: str, request: Request) -> StreamingResponse:
    worker = workers.get(camera_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="알 수 없는 카메라입니다")
    worker.start()
    async def frames():
        last_sent_version = -1
        while not await request.is_disconnected():
            with worker.lock:
                jpeg = worker.latest_jpeg
                frame_version = worker.frame_version
            if jpeg and frame_version != last_sent_version:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                last_sent_version = frame_version
            await asyncio.sleep(0.02)
    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/frames/{camera_id}")
def latest_frame(camera_id: str) -> Response:
    worker = workers.get(camera_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="camera not found")
    worker.start()
    with worker.lock:
        jpeg = worker.latest_jpeg
    if not jpeg:
        raise HTTPException(status_code=503, detail="frame is warming up")
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/events")
def events(after: int = Query(0, ge=0)) -> dict[str, Any]:
    with _event_lock:
        return {"events": [dict(event) for event in _events if event["id"] > after]}


@app.get("/snapshots/{snapshot_id}")
def snapshot(snapshot_id: str) -> Response:
    if not snapshot_id.isalnum():
        raise HTTPException(status_code=404, detail="캡처를 찾을 수 없습니다")
    image_path = SNAPSHOT_DIR / f"{snapshot_id}.jpg"
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="캡처를 찾을 수 없습니다")
    return Response(content=image_path.read_bytes(), media_type="image/jpeg")


@app.post("/reset")
def reset() -> dict[str, Any]:
    with _event_lock:
        _events.clear()
    for worker in workers.values():
        worker.reset()
    return {"status": "reset", "ready": True, "warmingUp": True}