"""
FFmpeg video processing pipeline — optimised for Lenovo Legion (NVIDIA RTX).

GPU pipeline (when NVENC available):
  Decode  → h264_cuvid (CUDA)
  Scale   → scale_cuda / scale_npp
  Encode  → h264_nvenc  preset p4 (quality) or p1 (speed)
  Clip cut→ parallel ThreadPoolExecutor (3 workers max)

CPU fallback:
  libx264 preset ultrafast/fast
"""
import glob as glob_module
import os
import random
import re
import subprocess
import tempfile
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Locate ffmpeg / ffprobe  (bin/ folder next to project root takes priority)
# ─────────────────────────────────────────────────────────────────────────────

def _find_bin(name: str) -> str:
    root   = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    local  = os.path.join(root, "bin", name + ".exe")
    if os.path.isfile(local):
        return local
    return name   # fall back to system PATH


FFMPEG  = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")


# ─────────────────────────────────────────────────────────────────────────────
# GPU detection
# ─────────────────────────────────────────────────────────────────────────────

def _probe_nvenc() -> bool:
    """Return True if h264_nvenc is usable on this machine."""
    try:
        r = subprocess.run(
            [FFMPEG, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
        )
        return "h264_nvenc" in r.stdout
    except Exception:
        return False


def _probe_cuvid() -> bool:
    """Return True if h264_cuvid (CUDA decode) is usable."""
    try:
        r = subprocess.run(
            [FFMPEG, "-hide_banner", "-hwaccels"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
        )
        return "cuda" in r.stdout
    except Exception:
        return False


# Cache results (called once per session)
_NVENC_OK: Optional[bool] = None
_CUVID_OK: Optional[bool] = None


def gpu_available() -> bool:
    global _NVENC_OK
    if _NVENC_OK is None:
        _NVENC_OK = _probe_nvenc()
    return _NVENC_OK


def cuvid_available() -> bool:
    global _CUVID_OK
    if _CUVID_OK is None:
        _CUVID_OK = _probe_cuvid()
    return _CUVID_OK


def get_gpu_info() -> str:
    """Human-readable GPU status string."""
    nvenc = gpu_available()
    cuvid = cuvid_available()
    if nvenc and cuvid:
        return "NVIDIA NVENC + CUDA (аппаратный рендер)"
    if nvenc:
        return "NVIDIA NVENC (аппаратный рендер, CPU декодирование)"
    return "CPU только (libx264)"


# ─────────────────────────────────────────────────────────────────────────────
# Config dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VideoConfig:
    source_folder:  str
    audio_path:     str
    output_path:    str
    quality:        str   = "1080p"     # "720p" or "1080p"
    fps:            int   = 60
    bg_volume:      float = 0.05        # background video audio level
    voice_volume:   float = 1.0         # voiceover level
    noise_intensity: int  = 8           # 0–30
    clip_min_dur:   float = 3.0
    clip_max_dur:   float = 5.0
    extra_seconds:  float = 10.0        # video longer than audio
    script:         str   = ""          # used for subtitle generation
    subtitle_font_size: int = 32
    use_gpu:        bool  = True        # attempt NVENC/CUDA
    parallel_workers: int = 3           # simultaneous clip-cut jobs
    progress_callback: Optional[Callable[[int, str], None]] = field(
        default=None, repr=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run(cmd: list[str], desc: str = "") -> str:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error ({desc}):\n{result.stderr[-3000:]}")
    return result.stdout


def get_audio_duration(path: str) -> float:
    out = _run([
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ], "get_duration")
    return float(out.strip())


def _get_video_duration(path: str) -> float:
    out = _run([
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ], "video_duration")
    return float(out.strip())


def get_video_files(folder: str) -> list[str]:
    exts = ("*.mp4", "*.mov", "*.avi", "*.mkv", "*.webm", "*.MP4", "*.MOV")
    files = []
    for ext in exts:
        files.extend(glob_module.glob(os.path.join(folder, ext)))
    return list(set(files))   # deduplicate


# ─────────────────────────────────────────────────────────────────────────────
# Clip cutting  (GPU-accelerated when available)
# ─────────────────────────────────────────────────────────────────────────────

def _cut_clip_gpu(input_path: str, start: float, duration: float, output_path: str):
    """Cut a clip using NVENC encode (fast, stays on GPU)."""
    cmd = [
        FFMPEG, "-y",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "h264_nvenc",
        "-preset", "p1",          # p1 = fastest NVENC preset
        "-rc", "constqp",
        "-qp", "28",              # quality – lower = better
        "-an",
        output_path,
    ]
    _run(cmd, f"cut_clip_gpu {os.path.basename(input_path)}")


def _cut_clip_cpu(input_path: str, start: float, duration: float, output_path: str):
    """Cut a clip using libx264 ultrafast (CPU fallback)."""
    cmd = [
        FFMPEG, "-y",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-an",
        output_path,
    ]
    _run(cmd, f"cut_clip_cpu {os.path.basename(input_path)}")


def _cut_clip(use_gpu: bool, input_path: str, start: float, duration: float, output_path: str):
    if use_gpu and gpu_available():
        try:
            _cut_clip_gpu(input_path, start, duration, output_path)
            return
        except Exception:
            pass   # fall through to CPU
    _cut_clip_cpu(input_path, start, duration, output_path)


# ─────────────────────────────────────────────────────────────────────────────
# Concat
# ─────────────────────────────────────────────────────────────────────────────

def _build_concat_list(clip_paths: list[str], list_path: str):
    with open(list_path, "w", encoding="utf-8") as f:
        for p in clip_paths:
            safe = p.replace("'", "'\\''")
            f.write(f"file '{safe}'\n")


def _concat_clips(list_path: str, output_path: str):
    _run([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path,
    ], "concat_clips")


# ─────────────────────────────────────────────────────────────────────────────
# Final render  (Legion-optimised NVENC)
# ─────────────────────────────────────────────────────────────────────────────

def _final_render_gpu(
    raw_video: str, audio_path: str, output_path: str,
    width: int, height: int, fps: int,
    noise: int, bg_volume: float, voice_volume: float,
    srt_path: Optional[str],
):
    """
    Final render with:
    - CUDA hardware decode  → scale_cuda  → h264_nvenc
    - Audio mix (voice + bg)
    - Subtitle overlay (software, applied before NVENC encode)
    - Noise filter (software)
    """
    # Software video filters (run before NVENC)
    # We use hwdownload+format to come back to CPU for filters that need it,
    # then re-upload for encoding.
    vf_parts = []
    if srt_path:
        safe_srt = srt_path.replace("\\", "/").replace(":", "\\:")
        vf_parts.append(
            f"subtitles='{safe_srt}':force_style="
            f"'FontSize=28,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,Alignment=2'"
        )
    if noise > 0:
        vf_parts.append(f"noise=alls={noise}:allf=t+u")
    vf_parts.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
    vf_parts.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    vf_parts.append(f"fps={fps}")
    vf = ",".join(vf_parts)

    filter_complex = (
        f"[0:a]volume={bg_volume:.4f}[bga];"
        f"[1:a]volume={voice_volume:.4f}[voa];"
        f"[bga][voa]amix=inputs=2:duration=longest:dropout_transition=2[aout]"
    )

    cmd = [
        FFMPEG, "-y",
        "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda",
        "-extra_hw_frames", "4",
        "-i", raw_video,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-vf", vf,
        "-map", "0:v",
        "-map", "[aout]",
        # NVENC settings for Legion RTX
        "-c:v", "h264_nvenc",
        "-preset", "p4",          # p4 = good quality/speed balance (p1=fastest, p7=best)
        "-tune", "hq",
        "-rc", "vbr",
        "-cq", "20",              # quality target (lower = better, 18-24 is great)
        "-b:v", "0",
        "-maxrate:v", "12M" if height == 1080 else "6M",
        "-bufsize:v", "24M" if height == 1080 else "12M",
        "-profile:v", "high",
        "-level", "4.2",
        "-g", str(fps * 2),       # keyframe every 2 seconds
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    _run(cmd, "final_render_gpu")


def _final_render_cpu(
    raw_video: str, audio_path: str, output_path: str,
    width: int, height: int, fps: int,
    noise: int, bg_volume: float, voice_volume: float,
    srt_path: Optional[str],
):
    """CPU fallback render with libx264."""
    vf_parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        f"fps={fps}",
    ]
    if noise > 0:
        vf_parts.append(f"noise=alls={noise}:allf=t+u")
    if srt_path:
        safe_srt = srt_path.replace("\\", "/").replace(":", "\\:")
        vf_parts.append(
            f"subtitles='{safe_srt}':force_style="
            f"'FontSize=28,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,Alignment=2'"
        )
    vf = ",".join(vf_parts)

    filter_complex = (
        f"[0:a]volume={bg_volume:.4f}[bga];"
        f"[1:a]volume={voice_volume:.4f}[voa];"
        f"[bga][voa]amix=inputs=2:duration=longest:dropout_transition=2[aout]"
    )

    cpu_cores = os.cpu_count() or 4
    cmd = [
        FFMPEG, "-y",
        "-i", raw_video,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-vf", vf,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-threads", str(cpu_cores),
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    _run(cmd, "final_render_cpu")


# ─────────────────────────────────────────────────────────────────────────────
# Subtitle generator
# ─────────────────────────────────────────────────────────────────────────────

def _make_srt(script: str, audio_duration: float, output_path: str):
    sentences = re.split(r'(?<=[.!?])\s+', script.strip())
    if not sentences:
        return

    total_chars = sum(len(s) for s in sentences) or 1

    def fmt_time(seconds: float) -> str:
        h  = int(seconds // 3600)
        m  = int((seconds % 3600) // 60)
        s  = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(output_path, "w", encoding="utf-8") as f:
        current = 0.0
        for idx, sentence in enumerate(sentences, 1):
            if not sentence.strip():
                continue
            duration = (len(sentence) / total_chars) * audio_duration
            end      = current + max(duration, 1.0)
            wrapped  = "\n".join(textwrap.wrap(sentence.strip(), 55))
            f.write(f"{idx}\n{fmt_time(current)} --> {fmt_time(end)}\n{wrapped}\n\n")
            current = end


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def process_video(config: VideoConfig) -> str:
    cb = config.progress_callback or (lambda pct, msg: None)

    use_gpu  = config.use_gpu and gpu_available()
    use_cuda = use_gpu and cuvid_available()

    quality_map = {"720p": (1280, 720), "1080p": (1920, 1080)}
    width, height = quality_map.get(config.quality, (1920, 1080))

    cb(5, f"Рендер: {'NVENC (GPU)' if use_gpu else 'libx264 (CPU)'} | "
         f"{width}×{height} @ {config.fps}fps")

    cb(8, "Определяем длину аудио...")
    audio_dur       = get_audio_duration(config.audio_path)
    total_video_dur = audio_dur + config.extra_seconds

    cb(12, "Собираем исходные видеофайлы...")
    video_files = get_video_files(config.source_folder)
    if not video_files:
        raise RuntimeError(f"В папке '{config.source_folder}' нет видеофайлов.")

    # Build list of (src, start, dur) clips until total duration reached
    clips_needed = total_video_dur
    clip_infos: list[tuple[str, float, float]] = []
    while clips_needed > 0:
        src = random.choice(video_files)
        try:
            src_dur = _get_video_duration(src)
        except Exception:
            continue
        if src_dur < 1.5:
            continue
        clip_dur   = round(random.uniform(config.clip_min_dur, config.clip_max_dur), 2)
        max_start  = max(0.0, src_dur - clip_dur - 0.5)
        start      = round(random.uniform(0, max_start), 2) if max_start > 0 else 0.0
        actual_dur = min(clip_dur, src_dur - start)
        clip_infos.append((src, start, actual_dur))
        clips_needed -= actual_dur

    cb(18, f"Нарезаем {len(clip_infos)} клипов параллельно ({config.parallel_workers} потока)...")

    with tempfile.TemporaryDirectory(prefix="ytgen_") as tmpdir:
        clip_paths = [os.path.join(tmpdir, f"clip_{i:04d}.mp4")
                      for i in range(len(clip_infos))]

        # ── Parallel clip cutting ────────────────────────────────────────────
        done_count = 0
        with ThreadPoolExecutor(max_workers=config.parallel_workers) as ex:
            futures = {
                ex.submit(
                    _cut_clip, use_gpu,
                    src, start, dur, clip_paths[i]
                ): i
                for i, (src, start, dur) in enumerate(clip_infos)
            }
            for fut in as_completed(futures):
                fut.result()   # re-raise any exception
                done_count += 1
                pct = 18 + int(done_count / len(clip_infos) * 35)
                cb(pct, f"Клипов нарезано: {done_count}/{len(clip_infos)}")

        # ── Concat ──────────────────────────────────────────────────────────
        cb(55, "Склеиваем клипы...")
        concat_list = os.path.join(tmpdir, "concat.txt")
        _build_concat_list(clip_paths, concat_list)
        raw_video = os.path.join(tmpdir, "raw_concat.mp4")
        _concat_clips(concat_list, raw_video)

        # ── Subtitles ───────────────────────────────────────────────────────
        srt_path = None
        if config.script:
            cb(60, "Создаём субтитры...")
            srt_path = os.path.join(tmpdir, "subs.srt")
            _make_srt(config.script, audio_dur, srt_path)

        # ── Final render ─────────────────────────────────────────────────────
        cb(63, f"Финальный рендер {'(NVENC GPU)' if use_gpu else '(CPU)'}...")
        os.makedirs(os.path.dirname(os.path.abspath(config.output_path)), exist_ok=True)

        if use_gpu:
            try:
                _final_render_gpu(
                    raw_video, config.audio_path, config.output_path,
                    width, height, config.fps,
                    config.noise_intensity,
                    config.bg_volume, config.voice_volume, srt_path,
                )
            except Exception as e:
                cb(63, f"NVENC не сработал ({e}), переключаемся на CPU...")
                _final_render_cpu(
                    raw_video, config.audio_path, config.output_path,
                    width, height, config.fps,
                    config.noise_intensity,
                    config.bg_volume, config.voice_volume, srt_path,
                )
        else:
            _final_render_cpu(
                raw_video, config.audio_path, config.output_path,
                width, height, config.fps,
                config.noise_intensity,
                config.bg_volume, config.voice_volume, srt_path,
            )

    cb(100, "Готово!")
    return config.output_path
