"""FFmpeg-based video processing pipeline."""
import glob as glob_module
import math
import os
import random
import re
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass, field
from typing import Callable, Optional


def _find_bin(name: str) -> str:
    """
    Look for ffmpeg/ffprobe in this order:
    1. <project_root>/bin/  (bundled copy)
    2. System PATH
    """
    # project root is two levels up from this file
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    local = os.path.join(root, "bin", name + ".exe")
    if os.path.isfile(local):
        return local
    return name   # fall back to PATH


FFMPEG = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")


@dataclass
class VideoConfig:
    source_folder: str
    audio_path: str
    output_path: str
    quality: str = "1080p"          # "720p" or "1080p"
    fps: int = 60
    bg_volume: float = 0.05         # 0.0 – 1.0 (background video audio)
    voice_volume: float = 1.0       # voiceover volume
    noise_intensity: int = 8        # 0-30
    clip_min_dur: float = 3.0
    clip_max_dur: float = 5.0
    extra_seconds: float = 10.0     # video longer than audio
    script: str = ""                # for subtitle generation
    subtitle_font_size: int = 32
    subtitle_font_color: str = "white"
    subtitle_outline_color: str = "black"
    subtitle_position: str = "bottom"  # "bottom" or "top"
    use_gpu: bool = True
    progress_callback: Optional[Callable[[int, str], None]] = field(
        default=None, repr=False
    )


def _run(cmd: list[str], desc: str = "") -> str:
    """Run a subprocess command and return stdout. Raises on error."""
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg error ({desc}):\n{result.stderr[-2000:]}"
        )
    return result.stdout


def get_audio_duration(path: str) -> float:
    """Return duration of an audio/video file in seconds."""
    out = _run([
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ], "get_duration")
    return float(out.strip())


def get_video_files(folder: str) -> list[str]:
    exts = ("*.mp4", "*.mov", "*.avi", "*.mkv", "*.webm")
    files = []
    for ext in exts:
        files.extend(glob_module.glob(os.path.join(folder, ext)))
    return files


def _get_video_duration(path: str) -> float:
    out = _run([
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ], "video_duration")
    return float(out.strip())


def _cut_clip(input_path: str, start: float, duration: float, output_path: str):
    _run([
        FFMPEG, "-y",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-an",          # strip audio from clips (we use voiceover)
        output_path,
    ], f"cut_clip {os.path.basename(input_path)}")


def _build_concat_list(clip_paths: list[str], list_path: str):
    with open(list_path, "w", encoding="utf-8") as f:
        for p in clip_paths:
            # escape single quotes
            safe = p.replace("'", "'\\''")
            f.write(f"file '{safe}'\n")


def _concat_clips(list_path: str, output_path: str):
    _run([
        FFMPEG, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path,
    ], "concat_clips")


def _scale_and_filter(
    input_path: str,
    output_path: str,
    width: int,
    height: int,
    fps: int,
    noise: int,
    use_gpu: bool,
    audio_path: str,
    bg_volume: float,
    voice_volume: float,
    srt_path: Optional[str] = None,
):
    """Final encode: scale, fps, noise, mix audio, add subtitles."""
    vf_parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        f"fps={fps}",
    ]
    if noise > 0:
        vf_parts.append(f"noise=alls={noise}:allf=t+u")
    if srt_path:
        # escape path for ffmpeg filtergraph
        safe_srt = srt_path.replace("\\", "/").replace(":", "\\:")
        vf_filter = (
            f"subtitles='{safe_srt}'"
            f":force_style='FontSize={28},PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
            f"Outline=2,Alignment=2'"
        )
        vf_parts.append(vf_filter)

    vf = ",".join(vf_parts)

    if use_gpu:
        vcodec = ["h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23"]
    else:
        vcodec = ["libx264", "-preset", "fast", "-crf", "23"]

    filter_complex = (
        f"[0:a]volume={bg_volume:.3f}[v_audio];"
        f"[1:a]volume={voice_volume:.3f}[voice];"
        f"[v_audio][voice]amix=inputs=2:duration=longest:dropout_transition=2[aout]"
    )

    cmd = [
        FFMPEG, "-y",
        "-i", input_path,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-vf", vf,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", *vcodec,
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    _run(cmd, "final_encode")


def _make_srt(script: str, audio_duration: float, output_path: str):
    """Create an SRT subtitle file from the script."""
    sentences = re.split(r'(?<=[.!?])\s+', script.strip())
    if not sentences:
        return

    total_chars = sum(len(s) for s in sentences)
    if total_chars == 0:
        return

    def fmt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(output_path, "w", encoding="utf-8") as f:
        current = 0.0
        for idx, sentence in enumerate(sentences, 1):
            if not sentence.strip():
                continue
            duration = (len(sentence) / total_chars) * audio_duration
            end = current + max(duration, 1.0)
            # wrap long lines
            wrapped = "\n".join(textwrap.wrap(sentence.strip(), 60))
            f.write(f"{idx}\n")
            f.write(f"{fmt_time(current)} --> {fmt_time(end)}\n")
            f.write(f"{wrapped}\n\n")
            current = end


def process_video(config: VideoConfig) -> str:
    """
    Full pipeline:
    1. Collect random clips from source folder
    2. Concat them
    3. Scale, apply filters, mix audio, add subtitles
    Returns path to output video.
    """
    cb = config.progress_callback or (lambda pct, msg: None)

    # Resolve output dimensions
    quality_map = {"720p": (1280, 720), "1080p": (1920, 1080)}
    width, height = quality_map.get(config.quality, (1920, 1080))

    cb(5, "Определяем длину аудио...")
    audio_dur = get_audio_duration(config.audio_path)
    total_video_dur = audio_dur + config.extra_seconds

    cb(10, "Собираем исходные видеофайлы...")
    video_files = get_video_files(config.source_folder)
    if not video_files:
        raise RuntimeError(f"В папке '{config.source_folder}' нет видеофайлов.")

    # Build clip list until total duration is reached
    cb(15, "Нарезаем случайные клипы...")
    clips_needed_dur = total_video_dur
    clip_infos = []  # list of (file, start, duration)

    while clips_needed_dur > 0:
        src = random.choice(video_files)
        try:
            src_dur = _get_video_duration(src)
        except Exception:
            continue
        if src_dur < 1.0:
            continue
        clip_dur = round(random.uniform(config.clip_min_dur, config.clip_max_dur), 2)
        max_start = max(0, src_dur - clip_dur - 0.5)
        start = round(random.uniform(0, max_start), 2) if max_start > 0 else 0.0
        clip_infos.append((src, start, min(clip_dur, src_dur - start)))
        clips_needed_dur -= clip_dur

    with tempfile.TemporaryDirectory(prefix="ytgen_") as tmpdir:
        cb(20, f"Вырезаем {len(clip_infos)} клипов...")
        clip_paths = []
        for i, (src, start, dur) in enumerate(clip_infos):
            out = os.path.join(tmpdir, f"clip_{i:04d}.mp4")
            _cut_clip(src, start, dur, out)
            clip_paths.append(out)
            pct = 20 + int((i + 1) / len(clip_infos) * 30)
            cb(pct, f"Клип {i + 1}/{len(clip_infos)}")

        cb(52, "Склеиваем клипы...")
        concat_list = os.path.join(tmpdir, "concat.txt")
        _build_concat_list(clip_paths, concat_list)
        raw_video = os.path.join(tmpdir, "raw_concat.mp4")
        _concat_clips(concat_list, raw_video)

        # Generate SRT
        srt_path = None
        if config.script:
            cb(60, "Создаём субтитры...")
            srt_path = os.path.join(tmpdir, "subtitles.srt")
            _make_srt(config.script, audio_dur, srt_path)

        cb(65, "Финальный рендер...")
        os.makedirs(os.path.dirname(os.path.abspath(config.output_path)), exist_ok=True)
        _scale_and_filter(
            input_path=raw_video,
            output_path=config.output_path,
            width=width,
            height=height,
            fps=config.fps,
            noise=config.noise_intensity,
            use_gpu=config.use_gpu,
            audio_path=config.audio_path,
            bg_volume=config.bg_volume,
            voice_volume=config.voice_volume,
            srt_path=srt_path,
        )

    cb(100, "Готово!")
    return config.output_path
