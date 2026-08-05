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