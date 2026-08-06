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