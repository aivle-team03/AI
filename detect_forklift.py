from pathlib import Path
from math import hypot
from collections import defaultdict

import cv2
from ultralytics import YOLO
import requests


# =========================================================
# 파일 경로
# =========================================================
BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = BASE_DIR / "person-forklift2-best.pt"
VIDEO_PATH = BASE_DIR / "test1.mp4"
OUTPUT_PATH = BASE_DIR / "forklift_tracking_result.mp4"


# =========================================================
# 모델 클래스
# =========================================================
FORKLIFT_CLASS_ID = 0
PERSON_CLASS_ID = 1

CONF_THRESHOLD = 0.4

EVENT_API_URL = "http://127.0.0.1:8000/api/ai/events"

FORKLIFT_CCTV_ID = 5
FORKLIFT_CATEGORY_ID = 1000006

# =========================================================
# 거리 및 위험 기준
# =========================================================
DANGER_DISTANCE_PX = 60
WARNING_DISTANCE_PX = 120

# 위험 거리 안에 이 시간 이상 머물러야 실제 위험으로 판정
DANGER_HOLD_SECONDS = 1.0

# 탐지가 잠깐 끊겨도 상태를 바로 삭제하지 않도록 허용
LOST_GRACE_SECONDS = 0.5


# =========================================================
# 화면 표시 설정
# =========================================================
POINT_RADIUS = 4
LINE_THICKNESS = 1

FORKLIFT_COLOR = (255, 0, 0)
SAFE_COLOR = (0, 255, 0)
WARNING_COLOR = (0, 165, 255)
DANGER_COLOR = (0, 0, 255)
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
    """바운딩 박스의 중심점을 계산합니다."""
    x1, y1, x2, y2 = box

    center_x = int((x1 + x2) / 2)
    center_y = int((y1 + y2) / 2)

    return center_x, center_y


def calculate_distance(point1, point2):
    """두 중심점 사이의 픽셀 거리를 계산합니다."""
    return hypot(
        point2[0] - point1[0],
        point2[1] - point1[1],
    )


def find_nearest_forklift(person_center, forklifts):
    """
    한 사람과 가장 가까운 지게차를 찾습니다.

    forklifts 형식:
    {
        track_id: (center_x, center_y)
    }
    """
    if not forklifts:
        return None, None, None

    nearest_id = None
    nearest_center = None
    nearest_distance = float("inf")

    for forklift_id, forklift_center in forklifts.items():
        distance = calculate_distance(
            person_center,
            forklift_center,
        )

        if distance < nearest_distance:
            nearest_id = forklift_id
            nearest_center = forklift_center
            nearest_distance = distance

    return nearest_id, nearest_center, nearest_distance


def get_motion_status(previous_distance, current_distance):
    """
    이전 거리와 현재 거리를 비교해 접근 또는 이탈 상태를 판단합니다.
    """
    if previous_distance is None:
        return "UNKNOWN"

    difference = current_distance - previous_distance

    # 미세한 흔들림은 정지 상태로 처리
    if abs(difference) < 1.5:
        return "STABLE"

    if difference < 0:
        return "APPROACHING"

    return "MOVING AWAY"


def draw_point(frame, center, color):
    """객체 중심점을 화면에 표시합니다."""
    cv2.circle(
        frame,
        center,
        POINT_RADIUS,
        color,
        -1,
        cv2.LINE_AA,
    )


def draw_label(frame, text, position, color):
    """화면에 텍스트를 표시합니다."""
    cv2.putText(
        frame,
        text,
        position,
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

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    writer = cv2.VideoWriter(
        str(OUTPUT_PATH),
        fourcc,
        fps,
        (width, height),
    )

    if not writer.isOpened():
        capture.release()
        raise RuntimeError(
            f"출력 영상을 만들 수 없습니다: {OUTPUT_PATH}"
        )

    # 각 사람-지게차 조합의 상태 저장
    pair_states = defaultdict(
        lambda: {
            "danger_frames": 0,
            "last_seen_frame": 0,
            "previous_distance": None,
            "minimum_distance": float("inf"),
            "danger_active": False,
            "alert_sent": False,
        }
    )

    frame_number = 0

    print("객체 추적을 시작합니다.")
    print(f"실제 위험 판정 기준: {DANGER_HOLD_SECONDS}초")
    print("실행 화면에서 q를 누르면 종료됩니다.")

    try:
        while True:
            success, frame = capture.read()

            if not success:
                break

            frame_number += 1

            # ByteTrack으로 객체 추적
            results = model.track(
                source=frame,
                conf=CONF_THRESHOLD,
                persist=True,
                tracker="bytetrack.yaml",
                verbose=False,
            )

            result = results[0]

            forklifts = {}
            persons = {}

            # 바운딩 박스는 그리지 않고 좌표와 추적 ID만 사용
            if (
                result.boxes is not None
                and result.boxes.id is not None
            ):
                boxes = result.boxes.xyxy.cpu().numpy()
                classes = result.boxes.cls.cpu().numpy()
                track_ids = (
                    result.boxes.id
                    .int()
                    .cpu()
                    .tolist()
                )

                for box, class_id, track_id in zip(
                    boxes,
                    classes,
                    track_ids,
                ):
                    x1, y1, x2, y2 = box.astype(int)

                    center = get_center(
                        (x1, y1, x2, y2)
                    )

                    class_id = int(class_id)
                    track_id = int(track_id)

                    if class_id == FORKLIFT_CLASS_ID:
                        forklifts[track_id] = center

                    elif class_id == PERSON_CLASS_ID:
                        persons[track_id] = center

            # 지게차 중심점 표시
            for forklift_id, forklift_center in forklifts.items():
                draw_point(
                    frame,
                    forklift_center,
                    FORKLIFT_COLOR,
                )

                draw_label(
                    frame,
                    f"Forklift {forklift_id}",
                    (
                        forklift_center[0] + 7,
                        forklift_center[1] - 7,
                    ),
                    FORKLIFT_COLOR,
                )

            active_pairs = set()
            danger_count = 0

            # 각 사람과 가장 가까운 지게차 계산
            for person_id, person_center in persons.items():
                (
                    forklift_id,
                    forklift_center,
                    distance,
                ) = find_nearest_forklift(
                    person_center,
                    forklifts,
                )

                # 지게차가 없는 경우 사람 중심점만 표시
                if forklift_id is None:
                    draw_point(
                        frame,
                        person_center,
                        SAFE_COLOR,
                    )

                    draw_label(
                        frame,
                        f"Person {person_id}",
                        (
                            person_center[0] + 7,
                            person_center[1] - 7,
                        ),
                        SAFE_COLOR,
                    )

                    continue

                pair_key = (person_id, forklift_id)
                active_pairs.add(pair_key)

                state = pair_states[pair_key]

                motion_status = get_motion_status(
                    state["previous_distance"],
                    distance,
                )

                state["previous_distance"] = distance
                state["last_seen_frame"] = frame_number
                state["minimum_distance"] = min(
                    state["minimum_distance"],
                    distance,
                )

                # 위험 거리 안에 있는 경우
                if distance <= DANGER_DISTANCE_PX:
                    state["danger_frames"] += 1

                else:
                    # 위험 거리 밖으로 벗어나면 연속 카운트 초기화
                    if state["danger_active"]:
                        duration = (
                            state["danger_frames"] / fps
                        )

                        print(
                            f"[위험 종료] "
                            f"Person {person_id} - "
                            f"Forklift {forklift_id} | "
                            f"지속시간: {duration:.2f}초 | "
                            f"최소 거리: "
                            f"{state['minimum_distance']:.0f}px"
                        )

                    state["danger_frames"] = 0
                    state["danger_active"] = False
                    state["alert_sent"] = False
                    state["minimum_distance"] = distance

                # 1초 이상 위험 거리 유지
                if (
                    state["danger_frames"]
                    >= danger_hold_frames
                ):
                
                    state["danger_active"] = True
                    danger_count += 1

                    if not state["alert_sent"]:
                        print(
                            f"[위험 발생] "
                            f"Person {person_id} - "
                            f"Forklift {forklift_id} | "
                            f"거리: {distance:.0f}px | "
                            f"상태: {motion_status}"
                        )

                        send_ai_event(
                            cctv_id=FORKLIFT_CCTV_ID,
                            category_id=FORKLIFT_CATEGORY_ID,
                        )

                        state["alert_sent"] = True
                # 화면 표시 상태 결정
                if state["danger_active"]:
                    display_status = "DANGER"
                    color = DANGER_COLOR

                elif distance <= DANGER_DISTANCE_PX:
                    remaining_frames = max(
                        0,
                        danger_hold_frames
                        - state["danger_frames"],
                    )

                    remaining_seconds = (
                        remaining_frames / fps
                    )

                    display_status = (
                        f"CHECK {remaining_seconds:.1f}s"
                    )
                    color = WARNING_COLOR

                elif distance <= WARNING_DISTANCE_PX:
                    display_status = "WARNING"
                    color = WARNING_COLOR

                else:
                    display_status = "SAFE"
                    color = SAFE_COLOR

                # 중심점 표시
                draw_point(
                    frame,
                    person_center,
                    color,
                )

                # 사람과 지게차 중심점 연결
                cv2.line(
                    frame,
                    person_center,
                    forklift_center,
                    color,
                    LINE_THICKNESS,
                    cv2.LINE_AA,
                )

                text_x = int(
                    (
                        person_center[0]
                        + forklift_center[0]
                    )
                    / 2
                )

                text_y = int(
                    (
                        person_center[1]
                        + forklift_center[1]
                    )
                    / 2
                )

                draw_label(
                    frame,
                    (
                        f"{distance:.0f}px "
                        f"{display_status} "
                        f"{motion_status}"
                    ),
                    (text_x, text_y - 5),
                    color,
                )

                draw_label(
                    frame,
                    f"Person {person_id}",
                    (
                        person_center[0] + 7,
                        person_center[1] - 7,
                    ),
                    color,
                )

            # 일정 시간 동안 다시 탐지되지 않은 조합 정리
            pairs_to_remove = []

            for pair_key, state in pair_states.items():
                frames_since_seen = (
                    frame_number
                    - state["last_seen_frame"]
                )

                if frames_since_seen > lost_grace_frames:
                    person_id, forklift_id = pair_key

                    if state["danger_active"]:
                        duration = (
                            state["danger_frames"] / fps
                        )

                        print(
                            f"[위험 추적 종료] "
                            f"Person {person_id} - "
                            f"Forklift {forklift_id} | "
                            f"지속시간: {duration:.2f}초 | "
                            f"최소 거리: "
                            f"{state['minimum_distance']:.0f}px"
                        )

                    pairs_to_remove.append(pair_key)

            for pair_key in pairs_to_remove:
                del pair_states[pair_key]

            # 화면 상단 정보
            cv2.putText(
                frame,
                (
                    f"Forklift: {len(forklifts)} | "
                    f"Person: {len(persons)} | "
                    f"Danger: {danger_count}"
                ),
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                TEXT_COLOR,
                2,
                cv2.LINE_AA,
            )

            writer.write(frame)

            cv2.imshow(
                "Forklift Safety Tracking",
                frame,
            )

            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("사용자가 실행을 종료했습니다.")
                break

    finally:
        capture.release()
        writer.release()
        cv2.destroyAllWindows()

    print(f"처리 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()