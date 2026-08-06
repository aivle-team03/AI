import os
import subprocess
from typing import List


def _get_ffmpeg_executable() -> str:
    """시스템 ffmpeg 실행 파일 또는 imageio_ffmpeg 번들 바이너리 경로 탐색"""
    import shutil
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return "ffmpeg"


def _concat_video_clips_ffmpeg(clip_paths: List[str], output_path: str) -> bool:
    """
    여러 개의 mp4 클립을 순서대로 하나의 영상으로 이어붙인다 (ffmpeg concat demuxer 사용).
    실패 시 False를 반환하며, 호출부에서 fallback 처리를 하도록 한다.
    """
    valid_clips = [c for c in clip_paths if c and os.path.exists(c) and os.path.getsize(c) > 0]
    if not valid_clips:
        print("[VeoGenerator] ERROR: 병합할 유효한 클립이 없습니다.")
        return False

    if len(valid_clips) == 1:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        import shutil
        shutil.copy(valid_clips[0], output_path)
        print("[VeoGenerator] INFO: 클립이 1개뿐이라 병합 없이 그대로 사용합니다.")
        return True

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    list_file = output_path + ".concat_list.txt"
    ffmpeg_bin = _get_ffmpeg_executable()

    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for clip in valid_clips:
                abs_path = os.path.abspath(clip).replace("'", "'\\''")
                f.write(f"file '{abs_path}'\n")

        cmd_copy = [
            ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", output_path
        ]
        result = subprocess.run(cmd_copy, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)

        if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            print(f"[VeoGenerator] WARNING: ffmpeg -c copy 병합 실패, 재인코딩 방식으로 재시도... ({result.stderr[-300:]})")
            cmd_reencode = [
                ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
                output_path
            ]
            result = subprocess.run(cmd_reencode, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)

        if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"[VeoGenerator] SUCCESS: {len(valid_clips)}개 클립 병합 완료 -> {output_path}")
            return True

        print(f"[VeoGenerator] ERROR: ffmpeg 병합 최종 실패: {result.stderr[-500:]}")
        return False
    except Exception as e:
        print(f"[VeoGenerator] ERROR: ffmpeg 병합 중 예외 발생: {e}")
        return False
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)


def _attach_audio_to_video_ffmpeg(video_path: str, audio_path: str, output_path: str) -> str:
    """FFmpeg를 사용해 한국어 고품질 Neural TTS 오디오(MP3)를 Veo 비디오 클립에 또박또박 믹싱/합성한다."""
    if not os.path.exists(video_path) or not os.path.exists(audio_path) or os.path.getsize(audio_path) < 100:
        return video_path

    ffmpeg_bin = _get_ffmpeg_executable()
    temp_output = output_path + ".muxed.mp4"
    cmd = [
        ffmpeg_bin, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        temp_output
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode == 0 and os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            import shutil
            shutil.move(temp_output, output_path)
            print(f"[VeoAudioMux] SUCCESS: 한국어 Neural TTS 오디오 병합 완료 -> {output_path}")
            return output_path
    except Exception as e:
        print(f"[VeoAudioMux] WARNING: 오디오 병합 중 예외 발생 (기존 오디오 사용): {e}")
        if os.path.exists(temp_output):
            os.remove(temp_output)
    return video_path
