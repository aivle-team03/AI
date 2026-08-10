from pathlib import Path

import cv2
from ultralytics import YOLO

import requests

# 파일 경로
BASE_DIR = Path(__file__).resolve().parent

# 실제 불·연기 모델 파일명으로 수정
MODEL_PATH = BASE_DIR / "fire_finetuned_v5.pt"

# 테스트할 영상 파일명으로 수정
VIDEO_PATH = BASE_DIR / "test3.mp4"

OUTPUT_PATH = BASE_DIR / "fire_detection_result.mp4"

EVENT_API_URL = "http://127.0.0.1:8000/api/ai/events"

FIRE_CCTV_ID = 3
SMOKE_CCTV_ID = 4

FIRE_CATEGORY_ID = 1
SMOKE_CATEGORY_ID = 2

# 탐지 설정
CONF_THRESHOLD = 0.4

# 불 또는 연기가 이 시간 이상 연속 탐지될 때 실제 위험으로 판정
DANGER_HOLD_SECONDS = 1.0

# 탐지가 잠깐 끊겨도 바로 위험 종료하지 않도록 허용
LOST_GRACE_SECONDS = 0.5

# 화면 표시 설정
BOX_THICKNESS = 1
POINT_RADIUS = 4

FIRE_COLOR = (0, 0, 255)
SMOKE_COLOR = (150, 150, 150)
NORMAL_COLOR = (0, 255, 0)
TEXT_COLOR = (255, 255, 255)


def send_ai_event(cctv_id: int, category_id: int):
    payload = {
        "cctv_id": cctv_id,
        "category_id": category_id,
        "image_url": None,
    }

    try:
        response = requests.post(
            EVENT_API_URL,
            json=payload,
            timeout=5,
        )

        response.raise_for_status()

        print("[이벤트 저장 성공]", response.json())

    except requests.RequestException as error:
        print("[이벤트 저장 실패]", error)

        if error.response is not None:
            print(error.response.text)


def get_center(box):
    """바운딩 박스 중심점을 계산합니다."""
    x1, y1, x2, y2 = box

    center_x = int((x1 + x2) / 2)
    center_y = int((y1 + y2) / 2)

    return center_x, center_y


def normalize_class_name(class_name):
    """모델 클래스 이름을 비교하기 쉬운 형태로 변경합니다."""
    return str(class_name).strip().lower()


def classify_detection(class_name):
    """
    클래스 이름을 fire 또는 smoke로 분류합니다.

    모델 클래스가 flame, flames, 불꽃 등인 경우도 일부 처리합니다.
    """
    name = normalize_class_name(class_name)

    fire_keywords = {
        "fire",
        "flame",
        "flames",
        "불",
        "불꽃",
        "화염",
    }

    smoke_keywords = {
        "smoke",
        "연기",
    }

    if name in fire_keywords:
        return "fire"

    if name in smoke_keywords:
        return "smoke"

    return None


def draw_detection(
    frame,
    box,
    center,
    label,
    confidence,
    color,
    danger_active,
):
    """탐지 결과를 화면에 표시합니다."""
    x1, y1, x2, y2 = box

    # 중심점 표시
    cv2.circle(
        frame,
        center,
        POINT_RADIUS,
        color,
        -1,
        cv2.LINE_AA,
    )

    # 불과 연기는 위치 확인이 중요하므로 얇은 박스도 표시
    cv2.rectangle(
        frame,
        (x1, y1),
        (x2, y2),
        color,
        BOX_THICKNESS,
    )

    status = "DANGER" if danger_active else "DETECTING"

    cv2.putText(
        frame,
        f"{label} {confidence:.2f} {status}",
        (x1, max(20, y1 - 7)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        color,
        1,
        cv2.LINE_AA,
    )


def main():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"모델 파일을 찾을 수 없습니다: {MODEL_PATH}"
        )

    if not VIDEO_PATH.exists():
        raise FileNotFoundError(
            f"영상 파일을 찾을 수 없습니다: {VIDEO_PATH}"
        )

    model = YOLO(str(MODEL_PATH))

    print("모델 클래스 정보:", model.names)

    capture = cv2.VideoCapture(str(VIDEO_PATH))

    if not capture.isOpened():
        raise RuntimeError(
            f"영상을 열 수 없습니다: {VIDEO_PATH}"
        )

    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if fps <= 0:
        fps = 30.0

    danger_hold_frames = max(
        1,
        int(fps * DANGER_HOLD_SECONDS),
    )

    lost_grace_frames = max(
        1,
        int(fps * LOST_GRACE_SECONDS),
    )

    writer = cv2.VideoWriter(
        str(OUTPUT_PATH),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        capture.release()
        raise RuntimeError(
            f"출력 영상을 만들 수 없습니다: {OUTPUT_PATH}"
        )

    fire_frames = 0
    smoke_frames = 0

    fire_lost_frames = 0
    smoke_lost_frames = 0

    fire_danger_active = False
    smoke_danger_active = False

    fire_alert_sent = False
    smoke_alert_sent = False

    frame_number = 0

    print("불·연기 탐지를 시작합니다.")
    print(f"위험 판정 기준: {DANGER_HOLD_SECONDS}초 연속 탐지")
    print("q를 누르면 종료됩니다.")

    try:
        while True:
            success, frame = capture.read()

            if not success:
                break

            frame_number += 1

            results = model.predict(
                source=frame,
                conf=CONF_THRESHOLD,
                verbose=False,
            )

            result = results[0]

            fire_detections = []
            smoke_detections = []

            if result.boxes is not None:
                for detected_box in result.boxes:
                    class_id = int(detected_box.cls[0].item())
                    confidence = float(
                        detected_box.conf[0].item()
                    )

                    class_name = model.names[class_id]
                    detection_type = classify_detection(
                        class_name
                    )

                    x1, y1, x2, y2 = (
                        detected_box.xyxy[0]
                        .cpu()
                        .numpy()
                        .astype(int)
                    )

                    center = get_center(
                        (x1, y1, x2, y2)
                    )

                    detection_data = {
                        "box": (x1, y1, x2, y2),
                        "center": center,
                        "confidence": confidence,
                        "class_name": str(class_name),
                    }

                    if detection_type == "fire":
                        fire_detections.append(
                            detection_data
                        )

                    elif detection_type == "smoke":
                        smoke_detections.append(
                            detection_data
                        )

            # =================================================
            # 불 지속시간 판정
            # =================================================
            if fire_detections:
                fire_frames += 1
                fire_lost_frames = 0

            else:
                fire_lost_frames += 1

                if fire_lost_frames > lost_grace_frames:
                    if fire_danger_active:
                        duration = fire_frames / fps

                        print(
                            f"[화재 위험 종료] "
                            f"지속시간: {duration:.2f}초"
                        )

                    fire_frames = 0
                    fire_danger_active = False
                    fire_alert_sent = False

            if fire_frames >= danger_hold_frames:
                fire_danger_active = True

                if not fire_alert_sent:
                    print(
                        f"[화재 위험 발생] "
                        f"프레임: {frame_number} | "
                        f"탐지 개수: {len(fire_detections)}"
                    )

                    send_ai_event(
                        cctv_id=FIRE_CCTV_ID,
                        category_id=FIRE_CATEGORY_ID,
                    )

                    fire_alert_sent = True

            # =================================================
            # 연기 지속시간 판정
            # =================================================
            if smoke_detections:
                smoke_frames += 1
                smoke_lost_frames = 0

            else:
                smoke_lost_frames += 1

                if smoke_lost_frames > lost_grace_frames:
                    if smoke_danger_active:
                        duration = smoke_frames / fps

                        print(
                            f"[연기 위험 종료] "
                            f"지속시간: {duration:.2f}초"
                        )

                    smoke_frames = 0
                    smoke_danger_active = False
                    smoke_alert_sent = False

            if smoke_frames >= danger_hold_frames:
                smoke_danger_active = True

                if not smoke_alert_sent:
                    print(
                        f"[연기 위험 발생] "
                        f"프레임: {frame_number} | "
                        f"탐지 개수: {len(smoke_detections)}"
                    )

                    send_ai_event(
                        cctv_id=SMOKE_CCTV_ID,
                        category_id=SMOKE_CATEGORY_ID,
                    )

                    smoke_alert_sent = True

            # =================================================
            # 탐지 결과 표시
            # =================================================
            for detection in fire_detections:
                draw_detection(
                    frame=frame,
                    box=detection["box"],
                    center=detection["center"],
                    label="FIRE",
                    confidence=detection["confidence"],
                    color=FIRE_COLOR,
                    danger_active=fire_danger_active,
                )

            for detection in smoke_detections:
                draw_detection(
                    frame=frame,
                    box=detection["box"],
                    center=detection["center"],
                    label="SMOKE",
                    confidence=detection["confidence"],
                    color=SMOKE_COLOR,
                    danger_active=smoke_danger_active,
                )

            danger_types = []

            if fire_danger_active:
                danger_types.append("FIRE")

            if smoke_danger_active:
                danger_types.append("SMOKE")

            if danger_types:
                overall_status = "DANGER: " + ", ".join(
                    danger_types
                )
                status_color = FIRE_COLOR
            else:
                overall_status = "NORMAL"
                status_color = NORMAL_COLOR

            cv2.putText(
                frame,
                (
                    f"Fire: {len(fire_detections)} | "
                    f"Smoke: {len(smoke_detections)}"
                ),
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                TEXT_COLOR,
                2,
                cv2.LINE_AA,
            )

            cv2.putText(
                frame,
                overall_status,
                (15, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                status_color,
                2,
                cv2.LINE_AA,
            )

            writer.write(frame)

            cv2.imshow(
                "Fire and Smoke Detection",
                frame,
            )

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        capture.release()
        writer.release()
        cv2.destroyAllWindows()

    print(f"탐지 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()