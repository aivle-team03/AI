from pathlib import Path
import math
import uuid
import subprocess

import cv2
from ultralytics import YOLO


BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = BASE_DIR / "person-forklift2-best.pt"
VIDEO_DIR = BASE_DIR / "videos"
OUTPUT_DIR = BASE_DIR / "outputs"

VIDEO_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


FORKLIFT_CLASS_ID = 0
PERSON_CLASS_ID = 1

# 테스트용으로 낮춤
CONF_THRESHOLD = 0.2

DANGER_DISTANCE_PX = 60
WARNING_DISTANCE_PX = 120

POINT_RADIUS = 8
LINE_THICKNESS = 3


if not MODEL_PATH.exists():
    raise FileNotFoundError(
        f"모델 파일을 찾을 수 없습니다: {MODEL_PATH}"
    )


# 서버 실행 시 모델을 한 번만 로드
model = YOLO(str(MODEL_PATH))

print("사용 중인 모델:", MODEL_PATH)
print("모델 클래스:", model.names)


def get_center(box):
    x1, y1, x2, y2 = box

    center_x = int((x1 + x2) / 2)
    center_y = int((y1 + y2) / 2)

    return center_x, center_y


def calculate_distance(point1, point2):
    return math.dist(point1, point2)


def get_distance_status(distance):
    if distance <= DANGER_DISTANCE_PX:
        return "DANGER", (0, 0, 255)

    if distance <= WARNING_DISTANCE_PX:
        return "WARNING", (0, 165, 255)

    return "SAFE", (0, 255, 0)


def draw_object_center(
    frame,
    object_data,
    label,
    color,
):
    center = object_data["point"]
    confidence = object_data["confidence"]

    cv2.circle(
        frame,
        center,
        POINT_RADIUS,
        color,
        -1,
    )

    cv2.putText(
        frame,
        f"{label} {confidence:.2f}",
        (center[0] + 5, center[1] - 5),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.35,
        color,
        1,
        cv2.LINE_AA,
    )


def analyze_video(
    video_path: str | Path,
    output_path: str | Path | None = None,
):
    video_path = Path(video_path)

    if not video_path.exists():
        raise FileNotFoundError(
            f"영상 파일을 찾을 수 없습니다: {video_path}"
        )

    if output_path is None:
        output_filename = (
            f"forklift_result_{uuid.uuid4().hex}.mp4"
        )
        output_path = OUTPUT_DIR / output_filename
    else:
        output_path = Path(output_path)
        output_filename = output_path.name

    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise RuntimeError(
            f"영상을 열 수 없습니다: {video_path}"
        )

    fps = cap.get(cv2.CAP_PROP_FPS)

    if fps <= 0:
        fps = 30

    width = int(
        cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    )

    height = int(
        cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    )

    if width <= 0 or height <= 0:
        cap.release()

        raise RuntimeError(
            "영상 크기를 확인할 수 없습니다."
        )

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    writer = cv2.VideoWriter(
        str(output_path),
        fourcc,
        fps,
        (width, height),
    )

    if not writer.isOpened():
        cap.release()

        raise RuntimeError(
            f"결과 영상을 생성할 수 없습니다: "
            f"{output_path}"
        )

    total_frames = 0
    danger_frames = 0
    warning_frames = 0
    minimum_distance = None

    total_forklift_detections = 0
    total_person_detections = 0

    frames_with_forklift = 0
    frames_with_person = 0
    frames_with_both = 0

    try:
        while True:
            success, frame = cap.read()

            if not success:
                break

            total_frames += 1

            result = model.predict(
                source=frame,
                conf=CONF_THRESHOLD,
                verbose=False,
            )[0]

            forklifts = []
            persons = []

            if result.boxes is not None:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])

                    x1, y1, x2, y2 = map(
                        int,
                        box.xyxy[0].tolist(),
                    )

                    object_data = {
                        "point": get_center(
                            (x1, y1, x2, y2)
                        ),
                        "confidence": confidence,
                    }

                    if class_id == FORKLIFT_CLASS_ID:
                        forklifts.append(
                            object_data
                        )

                        total_forklift_detections += 1

                    elif class_id == PERSON_CLASS_ID:
                        persons.append(
                            object_data
                        )

                        total_person_detections += 1

            if forklifts:
                frames_with_forklift += 1

            if persons:
                frames_with_person += 1

            if forklifts and persons:
                frames_with_both += 1

            for forklift in forklifts:
                draw_object_center(
                    frame,
                    forklift,
                    "forklift",
                    (255, 0, 255),
                )

            for person in persons:
                draw_object_center(
                    frame,
                    person,
                    "person",
                    (255, 200, 0),
                )

            frame_danger = False
            frame_warning = False

            for person in persons:
                if not forklifts:
                    continue

                person_point = person["point"]

                nearest_forklift = min(
                    forklifts,
                    key=lambda forklift:
                        calculate_distance(
                            person_point,
                            forklift["point"],
                        ),
                )

                forklift_point = (
                    nearest_forklift["point"]
                )

                distance = calculate_distance(
                    person_point,
                    forklift_point,
                )

                if (
                    minimum_distance is None
                    or distance < minimum_distance
                ):
                    minimum_distance = distance

                status, color = (
                    get_distance_status(distance)
                )

                if status == "DANGER":
                    frame_danger = True

                elif status == "WARNING":
                    frame_warning = True

                cv2.line(
                    frame,
                    person_point,
                    forklift_point,
                    color,
                    LINE_THICKNESS,
                    cv2.LINE_AA,
                )

                text_x = int(
                    (
                        person_point[0]
                        + forklift_point[0]
                    )
                    / 2
                )

                text_y = int(
                    (
                        person_point[1]
                        + forklift_point[1]
                    )
                    / 2
                )

                cv2.putText(
                    frame,
                    f"{distance:.0f}px",
                    (text_x + 3, text_y - 3),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    color,
                    1,
                    cv2.LINE_AA,
                )

            if frame_danger:
                danger_frames += 1

                cv2.putText(
                    frame,
                    "DANGER",
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )

            elif frame_warning:
                warning_frames += 1

                cv2.putText(
                    frame,
                    "WARNING",
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 165, 255),
                    2,
                    cv2.LINE_AA,
                )

            # 모델이 실제로 프레임을 분석했는지 확인용 표시
            cv2.putText(
                frame,
                (
                    f"forklift: {len(forklifts)} "
                    f"person: {len(persons)}"
                ),
                (10, height - 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

            writer.write(frame)

    finally:
        cap.release()
        writer.release()

    # =====================================================
    # 브라우저 재생용(H.264)으로 변환
    # =====================================================
    web_output_path = (
        output_path.parent /
        f"{output_path.stem}_web.mp4"
    )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(output_path),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(web_output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print(
        {
            "video": str(video_path),
            "output": str(web_output_path),
            "total_frames": total_frames,
            "forklift_detections": total_forklift_detections,
            "person_detections": total_person_detections,
            "frames_with_forklift": frames_with_forklift,
            "frames_with_person": frames_with_person,
            "frames_with_both": frames_with_both,
        }
    )

    return {
        "output_filename": web_output_path.name,
        "output_path": str(web_output_path),

        "danger_detected": danger_frames > 0,

        "total_frames": total_frames,
        "danger_frames": danger_frames,
        "warning_frames": warning_frames,

        "minimum_distance_px": (
            round(minimum_distance, 2)
            if minimum_distance is not None
            else None
        ),

        "forklift_detections":
            total_forklift_detections,

        "person_detections":
            total_person_detections,

        "frames_with_forklift":
            frames_with_forklift,

        "frames_with_person":
            frames_with_person,

        "frames_with_both":
            frames_with_both,
    }


if __name__ == "__main__":
    test_video = VIDEO_DIR / "test2.mp4"

    result = analyze_video(test_video)

    print("분석 완료")
    print(result)