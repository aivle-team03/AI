import argparse
import asyncio
import json

from app.pipeline import (
    create_veo_task_record,
    get_veo_task_status,
    process_veo_summary_video_pipeline,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="문서 파일로 Veo 안전 교육 영상을 생성한다 (서버 없이 단독 실행)."
    )
    parser.add_argument("file_path", help="교육 문서 경로 (PDF/PPTX/TXT)")
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--title", default=None)
    parser.add_argument("--category", default="공통")
    parser.add_argument("--type", default="필수")
    parser.add_argument("--request", default=None, help="영상 제작 요청사항 (선택)")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    task_id = create_veo_task_record()
    print(f"[VideoAgent] task_id={task_id}")

    asyncio.run(
        process_veo_summary_video_pipeline(
            task_id=task_id,
            file_path=args.file_path,
            company_id=args.company_id,
            title=args.title,
            category=args.category,
            type=args.type,
            request=args.request,
        )
    )

    print(
        json.dumps(
            get_veo_task_status(task_id),
            ensure_ascii=False,
            indent=2 if args.pretty else None,
        )
    )


if __name__ == "__main__":
    main()
