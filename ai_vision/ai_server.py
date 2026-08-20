"""BOSS CCTV AI 데모 서버.

실행: python -m uvicorn ai_server:app --host 127.0.0.1 --port 8002

테스트 영상은 이 AI 서비스가 소유하고, 프론트에는 분석 결과만 MJPEG로
제공한다. 위험 감지 시에는 캡처 URL과 함께 백엔드 이벤트 API에도 저장한다.
"""

from __future__ import annotations

import os
import asyncio
import json
import threading
import time
from uuid import uuid4
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

import cv2
import numpy as np
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from ultralytics import YOLO


BASE_DIR = Path(__file__).resolve().parent
# 객체 탐지 서비스 전용 설정을 사용한다. GPU EC2에는 이 파일만 배포한다.
load_dotenv(BASE_DIR / ".env")
BACKEND_URL = os.getenv("AI_BACKEND_URL", "http://127.0.0.1:8000")
PUBLIC_URL = os.getenv("AI_PUBLIC_URL", "http://127.0.0.1:8002")
MEDIA_URL_PREFIX = "/media/"
SNAPSHOT_S3_PREFIX = "media/ai-snapshots"


def upload_snapshot_to_s3(snapshot: bytes, camera_id: str) -> str:
    """Store an immutable detection image and return the DB media path.

    The backend's media convention stores paths (not an S3 URL) in the DB.
    Its response schemas turn `/media/...` into a CloudFront URL using
    `MEDIA_BASE_URL`.
    """
    bucket = os.getenv("AWS_S3_MEDIA_BUCKET")
    if not bucket:
        raise RuntimeError("AWS_S3_MEDIA_BUCKET is required for AI snapshots")

    object_path = f"{camera_id}/{time.strftime('%Y_%m_%d')}/{uuid4().hex}.jpg"
    key = f"{SNAPSHOT_S3_PREFIX}/{object_path}"
    try:
        boto3.client(
            "s3", region_name=os.getenv("AWS_REGION", "ap-northeast-2")
        ).put_object(
            Bucket=bucket,
            Key=key,
            Body=snapshot,
            ContentType="image/jpeg",
            CacheControl="public, max-age=31536000, immutable",
        )
    except (BotoCoreError, ClientError) as error:
        raise RuntimeError(f"AI snapshot S3 upload failed: {error}") from error
    return f"{SNAPSHOT_S3_PREFIX}/{object_path}"

# 소화장비 탐지 주기
INSPECTION_INTERVAL_SECONDS = int(os.getenv("AI_INSPECTION_INTERVAL_SECONDS", "600"))


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    source: Path
    category_name: str
    detector: str
    cctv_id: int
    category_id: int
    model_path: Path | None = None
    confidence: float = 0.4
    sample_fps: float = 1.0


@dataclass
class EquipmentInspection:
    """가장 최근 소화설비 자동 점검 결과다."""

    jpeg: bytes
    inspected_at: float
    source_time: float
    detected_count: int
    confidence: float
    is_hazard: bool
    reason: str | None = None


# ID 값은 현재 Dahyun AI 스크립트가 백엔드에 보내던 값을 유지한다.
# DB 시드가 다르면 환경 변수/설정으로 바꾸기 전에 실제 CCTV·카테고리 ID를 확인해야 한다.
CAMERAS = {
    "fire-01": CameraConfig(
        camera_id="fire-01",
        source=BASE_DIR / "test3.mp4",
        category_name="화재 감지",
        detector="fire",
        cctv_id=1,
        category_id=17,
        model_path=BASE_DIR / "fire_finetuned_v5.pt",
        sample_fps=10.0,
    ),
    "forklift-03": CameraConfig(
        camera_id="forklift-03",
        source=BASE_DIR / "test1.mp4",
        category_name="지게차 접근 위험",
        detector="forklift",
        cctv_id=2,
        category_id=20,
        model_path=BASE_DIR / "person-forklift2-best.pt",
        sample_fps=10.0,
    ),
    "extinguisher-01": CameraConfig(
        camera_id="extinguisher-01",
        source=BASE_DIR / "test8.mp4",
        category_name="소화기 미감지",
        detector="extinguisher",
        cctv_id=1,
        category_id=18,
        model_path=BASE_DIR / "fire extinguisher_best_v1.pt",
        sample_fps=1.0,
    ),
    "hydrant-01": CameraConfig(
        camera_id="hydrant-01",
        source=BASE_DIR / "test9.mp4",
        category_name="소화전 미감지",
        detector="hydrant",
        cctv_id=1,
        category_id=19,
        model_path=BASE_DIR / "fire hose station_best.pt",
        sample_fps=1.0,
    ),
}

# 소화기·소화전은 일반 위험 감지 스트림이 아니라, 설비 존재 여부를 주기적으로 점검한다.
STATIC_EQUIPMENT_DETECTORS = {"extinguisher", "hydrant"}

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
_server_instance_id = uuid4().hex
_equipment_inspections: dict[str, EquipmentInspection] = {}
_equipment_inspection_lock = threading.Lock()


def get_model(model_path: Path) -> YOLO:
    with _model_lock:
        if model_path not in _models:
            if not model_path.is_file():
                raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {model_path}")
            _models[model_path] = YOLO(str(model_path))
            print(f"모델 로드: {model_path.name}", flush=True)
        return _models[model_path]


def send_backend_event(config: CameraConfig, snapshot_url: str) -> None:
    """백엔드가 늦게 준비돼도 감지 이벤트를 잃지 않도록 별도 스레드에서 전송한다."""
    payload = json.dumps({
        "cctv_id": config.cctv_id,
        "category_id": config.category_id,
        "image_url": snapshot_url,
    }).encode("utf-8")
    # AI를 먼저 켜고 백엔드를 이어서 실행하는 경우가 있다. 기존 3초 재시도는
    # 백엔드 기동 전에 끝나서 화면의 임시 알림만 남고 DB 이벤트가 사라졌다.
    # 스트림 처리는 막지 않되, 백엔드가 준비될 시간을 충분히 준다.
    attempt = 0
    while True:
        attempt += 1
        request = UrlRequest(
            f"{BACKEND_URL}/api/ai/events", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                print(f"백엔드 이벤트 저장: {config.camera_id} ({response.status})", flush=True)
                return
        except HTTPError as error:
            # 4xx/5xx의 본문을 출력해야 category_id, DB 제약조건 같은 실제 원인을
            # AI 서버 콘솔에서 바로 확인할 수 있다.
            try:
                detail = error.read().decode("utf-8", errors="replace")
            except OSError:
                detail = ""
            # 잘못된 요청(4xx)은 재시도해도 해결되지 않는다. 반면 5xx는 백엔드
            # reload/DB 연결이 완료될 때까지 잠시 발생할 수 있으므로 이벤트를
            # 버리지 말고 계속 재시도한다.
            print(
                f"백엔드 이벤트 저장 실패 [{config.camera_id}] "
                f"HTTP {error.code} (시도 {attempt}): {detail}",
                flush=True,
            )
            if 400 <= error.code < 500:
                return
            time.sleep(1)
        except (URLError, TimeoutError) as error:
            print(
                f"백엔드 이벤트 저장 대기 [{config.camera_id}] "
                f"(시도 {attempt}): {error}",
                flush=True,
            )
            time.sleep(1)


def record_equipment_inspection(
    config: CameraConfig,
    *,
    jpeg: bytes,
    source_time: float,
    detected_count: int,
    confidence: float,
    is_hazard: bool,
    reason: str | None,
) -> None:
    """프론트가 최신 점검 이미지와 판정 결과를 조회할 수 있게 보관한다."""
    with _equipment_inspection_lock:
        _equipment_inspections[config.camera_id] = EquipmentInspection(
            jpeg=jpeg,
            inspected_at=time.time(),
            source_time=source_time,
            detected_count=detected_count,
            confidence=confidence,
            is_hazard=is_hazard,
            reason=reason,
        )


def publish_event(config: CameraConfig, confidence: float, source_time: float, snapshot: bytes) -> bool:
    global _next_event_id
    try:
        snapshot_url = upload_snapshot_to_s3(snapshot, config.camera_id)
    except RuntimeError as error:
        # 업로드 실패가 추론 worker를 멈추게 하거나 이미지 없는 이벤트를 남기면 안 된다.
        # 호출부는 False를 받아 다음 감지/점검에서 다시 시도한다.
        print(f"AI snapshot upload failed [{config.camera_id}]: {error}", flush=True)
        return False

    with _event_lock:
        event_id = _next_event_id
        _next_event_id += 1
        _events.append({
            "id": event_id,
            "cameraId": config.camera_id,
            "categoryName": config.category_name,
            "confidence": round(confidence, 3),
            "sourceTime": round(source_time, 2),
            "detectedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "snapshotUrl": snapshot_url,
        })
    # worker의 emitted_in_session이 한 서버 실행/데모 재시작 세션에서 한 번만
    # publish_event를 호출하도록 보장한다. 따라서 과거 실행의 파일 쿨다운 없이
    # 현재 세션 감지는 항상 DB에도 남긴다.
    threading.Thread(
        target=send_backend_event, args=(config, snapshot_url), daemon=True,
    ).start()
    return True


def _boxes_by_class(result: Any) -> tuple[list[tuple[tuple[int, int, int, int], float]], list[tuple[tuple[int, int, int, int], float]]]:
    """반환값은 (지게차 목록, 사람 목록)이며 각 요소는 (박스, 신뢰도)다."""
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
    """YOLO 기본 plot 대신 화재 화면에 맞춘 간결한 경고 표시를 그린다."""
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
    """Dahyun 방식: 바운딩박스 대신 중심점·거리선·위험 상태를 표시한다."""
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
            # 현재 프레임은 새 첫 프레임이 준비될 때까지 유지한다. 상세 화면에서
            # 돌아오거나 데모를 재시작할 때 검은 화면이 보이지 않게 하기 위함이다.
            self.consecutive_hits = 0
            self.emitted_in_session = False
            self.reset_requested = True
            self.reset_complete.clear()
        self.start()

    def is_hazard(self, result: Any) -> bool:
        if result.boxes is None or len(result.boxes) == 0:
            return False
        if self.config.detector == "fire":
            return True
        forklifts: list[tuple[int, int]] = []
        persons: list[tuple[int, int]] = []
        for box in result.boxes:
            class_id = int(box.cls[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            center = ((x1 + x2) // 2, (y1 + y2) // 2)
            if class_id == 0:
                forklifts.append(center)
            elif class_id == 1:
                persons.append(center)
        return any(
            ((px - fx) ** 2 + (py - fy) ** 2) ** 0.5 <= 60
            for px, py in persons for fx, fy in forklifts
        )

    def _run(self) -> None:
        capture = cv2.VideoCapture(str(self.config.source))
        if not capture.isOpened():
            raise RuntimeError(f"테스트 영상을 열 수 없습니다: {self.config.source}")
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        # 모델 로딩은 수 초가 걸릴 수 있다. 분석 준비 중에도 첫 원본 프레임을
        # 보내면 프론트 CCTV 탭이 검은 화면으로 오래 남지 않는다.
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
                confidence = float(result.boxes.conf.max()) if result.boxes is not None else 0.0
                self.emitted_in_session = publish_event(
                    self.config, confidence, frame_index / fps, jpeg
                )
            if jpeg:
                with self.lock:
                    self.latest_jpeg = jpeg
                    self.frame_version += 1
            time.sleep(max(0, 1 / self.config.sample_fps - (time.perf_counter() - started_at)))
        capture.release()


workers = {
    camera_id: CameraWorker(config) 
    for camera_id, config in CAMERAS.items() 
    if config.detector not in STATIC_EQUIPMENT_DETECTORS
}

_inspection_cursors: dict[str, int] = {}

def _run_equipment_inspector() -> None:
    time.sleep(5)
    while True:
        print(f"\n🔍 [자동 점검] 소화장비 존재 여부 검사를 시작합니다...", flush=True)
        for camera_id, config in CAMERAS.items():
            if config.detector not in STATIC_EQUIPMENT_DETECTORS:
                continue

            cap = cv2.VideoCapture(str(config.source))
            if not cap.isOpened():
                print(f"⚠️ [{camera_id}] 영상을 열 수 없습니다: {config.source}", flush=True)
                continue

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

            current_pos = _inspection_cursors.get(camera_id, 0)
            cap.set(cv2.CAP_PROP_POS_FRAMES, current_pos)

            ok, frame = cap.read()

            next_pos = (current_pos + int(fps * 3)) % total_frames
            _inspection_cursors[camera_id] = next_pos

            cap.release()

            if not ok or frame is None:
                print(f"⚠️ [{camera_id}] 프레임을 읽지 못했습니다.", flush=True)
                continue

            if not isinstance(config.model_path, Path) or not config.model_path.is_file():
                print(f"⚠️ [{camera_id}] 모델 파일이 없습니다: {config.model_path}", flush=True)
                continue

            model = get_model(config.model_path)
            result = model.predict(source=frame, conf=config.confidence, verbose=False)[0]
            detected_count = len(result.boxes) if result.boxes is not None else 0

            # 최고 신뢰도 계산
            max_conf = float(result.boxes.conf.max()) if (result.boxes is not None and len(result.boxes) > 0) else 0.0

            # YOLO 추론 결과(바운딩 박스 표시) 이미지 가져오기
            annotated_frame = result.plot()  # 박스, 신뢰도, 클래스명이 그려진 BGR 이미지

            # 바운딩 박스가 그려진 프레임을 JPEG로 인코딩
            encoded_ok, encoded = cv2.imencode(".jpg", annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not encoded_ok:
                print(f"⚠️ [{camera_id}] 점검 결과 이미지를 만들지 못했습니다.", flush=True)
                continue
            annotated_jpeg = encoded.tobytes()

            # 💡 [조건 변경] 감지된 개수가 0개이거나, 최고 신뢰도가 50% 미만인 경우 미감지(경고) 처리
            if detected_count == 0 or max_conf < 0.5:
                if detected_count == 0:
                    reason = "감지 객체 없음"
                else:
                    reason = f"낮은 신뢰도 ({max_conf:.0%} < 50%)"

                record_equipment_inspection(
                    config,
                    jpeg=annotated_jpeg,
                    source_time=current_pos / fps,
                    detected_count=detected_count,
                    confidence=max_conf,
                    is_hazard=True,
                    reason=reason,
                )

                print(f"🚨 [{config.category_name} 경고] {camera_id}: 미감지 판단 ({reason})! 이벤트 전송 중...", flush=True)
                
                publish_event(
                    config=config,
                    confidence=max_conf,  # 50% 미만이어도 측정된 신뢰도 전달 (없으면 0.0)
                    source_time=current_pos / fps,
                    snapshot=annotated_jpeg,
                )
            else:
                record_equipment_inspection(
                    config,
                    jpeg=annotated_jpeg,
                    source_time=current_pos / fps,
                    detected_count=detected_count,
                    confidence=max_conf,
                    is_hazard=False,
                    reason=None,
                )
                print(f"✅ [{config.category_name} 정상] {camera_id}: {detected_count}개 탐지됨 (신뢰도: {max_conf:.0%})", flush=True)

        time.sleep(INSPECTION_INTERVAL_SECONDS)


@app.on_event("startup")
def preload_models() -> None:
    all_model_paths = {
        config.model_path 
        for config in CAMERAS.values() 
        if isinstance(config.model_path, Path)
    }
    for model_path in all_model_paths:
        if model_path.is_file():
            model = get_model(model_path)
            model.predict(source=np.zeros((640, 640, 3), dtype=np.uint8), verbose=False)
            print(f"AI 모델 워밍업 완료: {model_path.name}", flush=True)

    threading.Thread(target=_run_equipment_inspector, name="ai-extinguisher-inspector", daemon=True).start()
    print(f"소화장비 자동 점검 스케줄러 가동 완료 (주기: {INSPECTION_INTERVAL_SECONDS}초)", flush=True)


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
            # 같은 JPEG를 매 0.02초마다 재전송하지 않는다. 클라이언트마다
            # 새 분석 프레임이 만들어졌을 때 한 번만 전송한다.
            if jpeg and frame_version != last_sent_version:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                last_sent_version = frame_version
            await asyncio.sleep(0.02)
    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/frames/{camera_id}")
def latest_frame(camera_id: str) -> Response:
    """Return the most recent image immediately while a new MJPEG client connects."""
    worker = workers.get(camera_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="camera not found")
    worker.start()
    with worker.lock:
        jpeg = worker.latest_jpeg
    if not jpeg:
        raise HTTPException(status_code=503, detail="frame is warming up")
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/equipment/status")
def equipment_status() -> dict[str, Any]:
    """소화기·소화전 자동 점검 카드에 표시할 최신 상태를 반환한다."""
    with _equipment_inspection_lock:
        inspections = dict(_equipment_inspections)

    equipment = []
    for camera_id, config in CAMERAS.items():
        if config.detector not in STATIC_EQUIPMENT_DETECTORS:
            continue

        inspection = inspections.get(camera_id)
        item: dict[str, Any] = {
            "cameraId": camera_id,
            "categoryName": config.category_name,
            "detector": config.detector,
            "imageUrl": f"{PUBLIC_URL}/equipment/{camera_id}/frame",
        }
        if inspection is None:
            item["status"] = "warming_up"
        else:
            item.update({
                "status": "warning" if inspection.is_hazard else "normal",
                "detectedCount": inspection.detected_count,
                "confidence": inspection.confidence,
                "inspectedAt": inspection.inspected_at,
                "sourceTime": inspection.source_time,
                "reason": inspection.reason,
            })
        equipment.append(item)

    return {"inspectionIntervalSeconds": INSPECTION_INTERVAL_SECONDS, "equipment": equipment}


@app.get("/equipment/{camera_id}/frame")
def equipment_frame(camera_id: str) -> Response:
    """최근 자동 점검에서 바운딩 박스를 그린 이미지 한 장을 반환한다."""
    if camera_id not in CAMERAS or CAMERAS[camera_id].detector not in STATIC_EQUIPMENT_DETECTORS:
        raise HTTPException(status_code=404, detail="equipment camera not found")

    with _equipment_inspection_lock:
        inspection = _equipment_inspections.get(camera_id)
    if inspection is None:
        raise HTTPException(status_code=503, detail="inspection is warming up")
    return Response(
        content=inspection.jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/events")
def events(after: int = Query(0, ge=0)) -> dict[str, Any]:
    with _event_lock:
        return {
            "serverInstanceId": _server_instance_id,
            "events": [dict(event) for event in _events if event["id"] > after],
        }


@app.post("/reset")
def reset() -> dict[str, Any]:
    with _event_lock:
        _events.clear()
    for worker in workers.values():
        worker.reset()
    # 모델의 첫 로딩을 기다리지 않는다. 각 worker는 원본 첫 프레임을 먼저
    # 내보내므로 프론트는 즉시 화면을 그리고, 준비되면 분석 프레임으로 전환한다.
    return {"status": "reset", "ready": True, "warmingUp": True}
