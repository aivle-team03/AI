from pathlib import Path
import math

import cv2
from ultralytics import YOLO

# 경로 설정
BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = BASE_DIR / "person-forklift2-best.pt"
VIDEO_PATH = BASE_DIR / "test.mp4"
OUTPUT_PATH = BASE_DIR / "distance_result.mp4"


# 모델 클래스
FORKLIFT_CLASS_ID = 0
PERSON_CLASS_ID = 1


# 탐지 및 거리 설정
CONF_THRESHOLD = 0.4

# 영상이 작으므로 거리 기준 축소
DANGER_DISTANCE_PX = 60
WARNING_DISTANCE_PX = 120

# 표시 크기
POINT_RADIUS = 3
LINE_THICKNESS = 1


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


def draw_object_center(frame, object_data, label, color):

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

    print("모델 클래스:", model.names)

    cap = cv2.VideoCapture(str(VIDEO_PATH))

    if not cap.isOpened():
        raise RuntimeError(
            f"영상을 열 수 없습니다: {VIDEO_PATH}"
        )

    fps = cap.get(cv2.CAP_PROP_FPS)

    if fps <= 0:
        fps = 30

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    writer = cv2.VideoWriter(
        str(OUTPUT_PATH),
        fourcc,
        fps,
        (width, height),
    )

    if not writer.isOpened():
        cap.release()
        raise RuntimeError(
            f"결과 영상을 생성할 수 없습니다: {OUTPUT_PATH}"
        )

    while True:
        success, frame = cap.read()

        if not success:
            break

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
                    forklifts.append(object_data)

                elif class_id == PERSON_CLASS_ID:
                    persons.append(object_data)

        # 지게차 중심점 표시
        for forklift in forklifts:
            draw_object_center(
                frame=frame,
                object_data=forklift,
                label="forklift",
                color=(255, 0, 255),
            )

        # 사람 중심점 표시
        for person in persons:
            draw_object_center(
                frame=frame,
                object_data=person,
                label="person",
                color=(255, 200, 0),
            )

        danger_detected = False

        # 각 사람과 가장 가까운 지게차 사이 거리 계산
        for person in persons:
            if not forklifts:
                continue

            person_point = person["point"]

            nearest_forklift = min(
                forklifts,
                key=lambda forklift: calculate_distance(
                    person_point,
                    forklift["point"],
                ),
            )

            forklift_point = nearest_forklift["point"]

            distance = calculate_distance(
                person_point,
                forklift_point,
            )

            status, color = get_distance_status(distance)

            if status == "DANGER":
                danger_detected = True

            # 얇은 연결선
            cv2.line(
                frame,
                person_point,
                forklift_point,
                color,
                LINE_THICKNESS,
                cv2.LINE_AA,
            )

            # 선 중간 좌표
            text_x = int(
                (person_point[0] + forklift_point[0]) / 2
            )

            text_y = int(
                (person_point[1] + forklift_point[1]) / 2
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

        if danger_detected:
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

        writer.write(frame)

        # 영상이 작으면 화면에 확대해서 표시
        display_scale = 2

        display_frame = cv2.resize(
            frame,
            None,
            fx=display_scale,
            fy=display_scale,
            interpolation=cv2.INTER_NEAREST,
        )

        cv2.imshow(
            "Forklift Person Distance",
            display_frame,
        )

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    writer.release()
    cv2.destroyAllWindows()

    print(f"완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()