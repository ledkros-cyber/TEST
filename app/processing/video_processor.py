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
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    from app.utils.logger import log
except Exception:
    log = None


# ─────────────────────────────────────────────────────────────────────────────
# Windows: suppress black console popup windows for every subprocess call
# ─────────────────────────────────────────────────────────────────────────────

_POPEN_FLAGS: dict = {}
if sys.platform == "win32":
    _POPEN_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW


# ─────────────────────────────────────────────────────────────────────────────
# Locate ffmpeg / ffprobe  (bin/ folder next to project root takes priority)
# ─────────────────────────────────────────────────────────────────────────────

def _find_bin(name: str) -> str:
    root  = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    local = os.path.join(root, "bin", name + ".exe")
    if os.path.isfile(local):
        return local
    return name   # fall back to system PATH


FFMPEG  = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")


# ─────────────────────────────────────────────────────────────────────────────
# GPU detection
# ─────────────────────────────────────────────────────────────────────────────

def _probe_nvenc() -> bool:
    try:
        r = subprocess.run(
            [FFMPEG, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=10, **_POPEN_FLAGS,
        )
        return "h264_nvenc" in r.stdout
    except Exception:
        return False


def _probe_cuvid() -> bool:
    try:
        r = subprocess.run(
            [FFMPEG, "-hide_banner", "-hwaccels"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=10, **_POPEN_FLAGS,
        )
        return "cuda" in r.stdout
    except Exception:
        return False


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
    quality:        str   = "1080p"
    fps:            int   = 30
    voice_volume:   float = 1.0
    noise_intensity: int  = 8
    clip_min_dur:   float = 3.0
    clip_max_dur:   float = 5.0
    extra_seconds:  float = 10.0
    script:         str   = ""
    use_gpu:        bool  = True
    parallel_workers: int = 2
    bg_music_path:  str   = ""      # optional background music file
    bg_music_volume: float = 0.12  # background music volume (0.0–1.0)
    progress_callback: Optional[Callable[[int, str], None]] = field(
        default=None, repr=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run(cmd: list[str], desc: str = "",
         progress_cb: Optional[Callable[[int, str], None]] = None,
         progress_start: int = 63, progress_end: int = 98,
         total_duration: float = 0.0) -> str:
    """Run a command; on failure show the real FFmpeg error, not the banner.

    If progress_cb is provided and total_duration > 0, reads FFmpeg stderr
    in real-time and maps encoded time → progress percentage.
    """
    if progress_cb and total_duration > 0:
        # Real-time progress: read stderr line by line
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **_POPEN_FLAGS,
        )
        stderr_lines: list[str] = []
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            # FFmpeg writes "time=HH:MM:SS.ms" in the progress line
            m = re.search(r"time=(\d+):(\d+):([\d.]+)", line)
            if m:
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                frac = min(t / total_duration, 1.0)
                pct  = progress_start + int(frac * (progress_end - progress_start))
                elapsed_str = f"{int(t // 60)}:{int(t % 60):02d}"
                total_str   = f"{int(total_duration // 60)}:{int(total_duration % 60):02d}"
                progress_cb(pct, f"Рендер: {elapsed_str} / {total_str}")
        proc.wait()
        if proc.returncode != 0:
            stderr = "".join(stderr_lines)
            lines  = stderr.splitlines()
            start = 0
            for i, ln in enumerate(lines):
                if ln.strip() == "" and i > 0:
                    start = i + 1
                    break
            relevant = lines[start:][-60:]
            msg = "\n".join(relevant) if relevant else stderr[-2000:]
            raise RuntimeError(f"FFmpeg error ({desc}):\n{msg}")
        return ""

    # Normal blocking run (no progress tracking)
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **_POPEN_FLAGS,
    )
    if result.returncode != 0:
        stderr = result.stderr
        lines  = stderr.splitlines()
        start = 0
        for i, ln in enumerate(lines):
            if ln.strip() == "" and i > 0:
                start = i + 1
                break
        relevant = lines[start:][-60:]
        msg = "\n".join(relevant) if relevant else stderr[-2000:]
        raise RuntimeError(f"FFmpeg error ({desc}):\n{msg}")
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
    return list(set(files))


# ─────────────────────────────────────────────────────────────────────────────
# Clip cutting
# ─────────────────────────────────────────────────────────────────────────────

def _cut_clip_gpu(input_path: str, start: float, duration: float,
                  output_path: str, fps: int = 30,
                  width: int = 1920, height: int = 1080):
    # Normalize resolution + FPS at cut time so all clips are identical for concat.
    # This prevents NVENC "Reconfiguring filter graph" crash when source clips
    # have mixed resolutions (e.g. 4K + 1080p in the same folder).
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={fps}"
    )
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-ss", str(start), "-i", input_path, "-t", str(duration),
        "-vf", vf,
        "-c:v", "h264_nvenc", "-preset", "p1", "-rc", "constqp", "-qp", "28",
        "-an",
        "-video_track_timescale", "90000",
        output_path,
    ], f"cut_clip_gpu {os.path.basename(input_path)}")


def _cut_clip_cpu(input_path: str, start: float, duration: float,
                  output_path: str, fps: int = 30,
                  width: int = 1920, height: int = 1080):
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={fps}"
    )
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-ss", str(start), "-i", input_path, "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-an",
        "-video_track_timescale", "90000",
        output_path,
    ], f"cut_clip_cpu {os.path.basename(input_path)}")


def _cut_clip(use_gpu: bool, input_path: str, start: float,
              duration: float, output_path: str,
              fps: int = 30, width: int = 1920, height: int = 1080):
    if use_gpu and gpu_available():
        try:
            _cut_clip_gpu(input_path, start, duration, output_path,
                          fps=fps, width=width, height=height)
            return
        except Exception:
            pass
    _cut_clip_cpu(input_path, start, duration, output_path,
                  fps=fps, width=width, height=height)


# ─────────────────────────────────────────────────────────────────────────────
# Concat
# ─────────────────────────────────────────────────────────────────────────────

def _build_concat_list(clip_paths: list[str], list_path: str):
    with open(list_path, "w", encoding="utf-8") as f:
        for p in clip_paths:
            safe = p.replace("\\", "/")
            f.write(f"file '{safe}'\n")


def _concat_clips(list_path: str, output_path: str):
    # -fflags +genpts regenerates presentation timestamps — prevents frozen frames
    # when clips have slightly different timescales after cutting
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-fflags", "+genpts",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ], "concat_clips")


# ─────────────────────────────────────────────────────────────────────────────
# Subtitle helper
# ─────────────────────────────────────────────────────────────────────────────

def _srt_filter(srt_path: str) -> str:
    """Build a safe subtitles= filter string for Windows paths."""
    safe = srt_path.replace("\\", "/")
    safe = re.sub(r"^([A-Za-z]):/", r"\1\\:/", safe)
    return (
        f"subtitles='{safe}':force_style="
        f"'FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
        f"Outline=2,Shadow=1,Alignment=2,MarginV=45,Bold=1'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Final render — GPU (NVENC)
# ─────────────────────────────────────────────────────────────────────────────

def _build_audio_filter(voice_volume: float,
                        bg_music_path: str = "",
                        bg_music_volume: float = 0.12,
                        voice_input_idx: int = 1,
                        bg_input_idx: int = 2) -> tuple[list[str], str]:
    """Build FFmpeg audio filter graph for voiceover + optional background music.

    Returns (extra_inputs, af_or_filter_complex_args).
    If bg_music_path is set: returns filter_complex mixing voice + bg music.
    Otherwise: returns simple -af volume=... args.
    """
    if bg_music_path and os.path.isfile(bg_music_path):
        # Mix voiceover + background music
        # Voice at voice_volume, bg music at bg_music_volume, loop bg to match
        fc = (
            f"[{voice_input_idx}:a]volume={voice_volume:.4f}[v];"
            f"[{bg_input_idx}:a]volume={bg_music_volume:.4f}[b];"
            f"[v][b]amix=inputs=2:duration=first:dropout_transition=3[aout]"
        )
        return ["-stream_loop", "-1", "-i", bg_music_path], fc
    else:
        return [], ""


def _final_render_gpu(
    raw_video: str, audio_path: str, output_path: str,
    width: int, height: int, fps: int,
    noise: int, voice_volume: float,
    srt_path: Optional[str],
    bg_music_path: str = "",
    bg_music_volume: float = 0.12,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    total_duration: float = 0.0,
):
    # Clips are already normalized to target resolution+fps during cutting.
    # Only apply subtitle and noise filters here — no scale/pad/fps needed.
    vf_parts = []
    if srt_path:
        vf_parts.append(_srt_filter(srt_path))
    if noise > 0:
        vf_parts.append(f"noise=alls={noise}:allf=t+u")
    vf = ",".join(vf_parts) if vf_parts else "null"

    bg_extra, fc = _build_audio_filter(
        voice_volume, bg_music_path, bg_music_volume,
        voice_input_idx=1, bg_input_idx=2,
    )

    cmd = [
        FFMPEG, "-y", "-hide_banner",
        "-hwaccel", "cuda",
        "-i", raw_video, "-i", audio_path,
    ]
    cmd += bg_extra
    cmd += ["-vf", vf]

    if fc:
        # filter_complex for mixed audio
        cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a", "-af", f"volume={voice_volume:.4f}"]

    cmd += [
        "-c:v", "h264_nvenc",
        "-preset", "p3",
        "-tune", "hq",
        "-rc", "vbr", "-cq", "23", "-b:v", "0",
        "-maxrate:v", "8M" if height == 1080 else "4M",
        "-bufsize:v", "16M" if height == 1080 else "8M",
        "-profile:v", "high", "-level", "4.2",
        "-g", str(fps * 2),
        "-spatial-aq", "1",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    _run(cmd, "final_render_gpu", progress_cb=progress_cb,
         progress_start=63, progress_end=98, total_duration=total_duration)


# ─────────────────────────────────────────────────────────────────────────────
# Final render — CPU (libx264)
# ─────────────────────────────────────────────────────────────────────────────

def _final_render_cpu(
    raw_video: str, audio_path: str, output_path: str,
    width: int, height: int, fps: int,
    noise: int, voice_volume: float,
    srt_path: Optional[str],
    bg_music_path: str = "",
    bg_music_volume: float = 0.12,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    total_duration: float = 0.0,
):
    # Clips already normalized — only apply subtitle/noise filters
    vf_parts = []
    if noise > 0:
        vf_parts.append(f"noise=alls={noise}:allf=t+u")
    if srt_path:
        vf_parts.append(_srt_filter(srt_path))
    vf = ",".join(vf_parts) if vf_parts else "null"

    bg_extra, fc = _build_audio_filter(
        voice_volume, bg_music_path, bg_music_volume,
        voice_input_idx=1, bg_input_idx=2,
    )

    cpu_cores = os.cpu_count() or 8
    cmd = [
        FFMPEG, "-y", "-hide_banner",
        "-i", raw_video, "-i", audio_path,
    ]
    cmd += bg_extra
    cmd += ["-vf", vf]

    if fc:
        cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a", "-af", f"volume={voice_volume:.4f}"]

    cmd += [
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-tune", "fastdecode",
        "-threads", str(cpu_cores),
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    _run(cmd, "final_render_cpu", progress_cb=progress_cb,
         progress_start=63, progress_end=98, total_duration=total_duration)


def _final_render_cpu_no_subs(
    raw_video: str, audio_path: str, output_path: str,
    width: int, height: int, fps: int,
    noise: int, voice_volume: float,
    bg_music_path: str = "",
    bg_music_volume: float = 0.12,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    total_duration: float = 0.0,
):
    """CPU render without subtitle filter — fallback when subtitles cause errors."""
    vf_parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        f"fps={fps}",
    ]
    if noise > 0:
        vf_parts.append(f"noise=alls={noise}:allf=t+u")
    vf = ",".join(vf_parts)

    bg_extra, fc = _build_audio_filter(
        voice_volume, bg_music_path, bg_music_volume,
        voice_input_idx=1, bg_input_idx=2,
    )
    cpu_cores = os.cpu_count() or 4
    cmd = [FFMPEG, "-y", "-hide_banner", "-i", raw_video, "-i", audio_path]
    cmd += bg_extra
    cmd += ["-vf", vf]
    if fc:
        cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a", "-af", f"volume={voice_volume:.4f}"]
    cmd += [
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-threads", str(cpu_cores),
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    _run(cmd, "final_render_cpu_no_subs", progress_cb=progress_cb,
         progress_start=65, progress_end=98, total_duration=total_duration)


# ─────────────────────────────────────────────────────────────────────────────
# Subtitle generator
# ─────────────────────────────────────────────────────────────────────────────

def _clean_script_for_subs(script: str) -> str:
    """Remove stage directions and narrator labels from script for subtitles."""
    # Remove (Visual: ...) and similar parenthetical stage directions
    text = re.sub(r'\(.*?\)', '', script, flags=re.DOTALL)
    # Remove "Narrator:" / "Голос за кадром:" prefixes
    text = re.sub(r'(?i)^(narrator|голос за кадром|speaker|voice|диктор)\s*:\s*', '', text, flags=re.MULTILINE)
    # Collapse extra blank lines and spaces
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def _split_into_one_liners(text: str, max_chars: int = 55) -> list[str]:
    """Split text into single-line chunks of max_chars each.
    One subtitle entry = ONE line only (no wrapping to second line).
    """
    words = text.split()
    chunks: list[str] = []
    line = ""
    for word in words:
        test = (line + " " + word).strip() if line else word
        if len(test) <= max_chars:
            line = test
        else:
            if line:
                chunks.append(line)
            line = word
    if line:
        chunks.append(line)
    return [c for c in chunks if c.strip()]


def _make_srt(script: str, audio_duration: float, output_path: str):
    """Generate SRT subtitles with word-count-based timing for better sync."""
    clean = _clean_script_for_subs(script)
    # Split into phrases by sentence-ending punctuation
    sentences = re.split(r'(?<=[.!?])\s+', clean)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return

    # Each sentence → one-line subtitle chunks (max 55 chars)
    chunks: list[str] = []
    for sent in sentences:
        chunks.extend(_split_into_one_liners(sent, max_chars=55))

    if not chunks:
        return

    # ── Better timing: word count + punctuation pause weights ────────────────
    # Average TTS speaking rate ~2.5 words/sec. Pauses after periods: +0.25s
    WORDS_PER_SEC = 2.5
    PAUSE_PERIOD  = 0.30   # pause after sentence ending (. ! ?)
    PAUSE_COMMA   = 0.12   # pause after comma/semicolon in previous chunk

    # Pre-calculate duration for each chunk
    durations: list[float] = []
    for i, chunk in enumerate(chunks):
        words = len(chunk.split())
        base  = words / WORDS_PER_SEC
        # Add pause if chunk ends with sentence-ending punctuation
        pause = PAUSE_PERIOD if chunk.rstrip()[-1:] in ".!?" else PAUSE_COMMA
        durations.append(max(base + pause, 0.6))

    # Scale durations proportionally to fit exactly into audio_duration
    total_raw = sum(durations)
    if total_raw > 0:
        scale = audio_duration / total_raw
        durations = [d * scale for d in durations]

    def fmt_time(seconds: float) -> str:
        h  = int(seconds // 3600)
        m  = int((seconds % 3600) // 60)
        s  = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(output_path, "w", encoding="utf-8") as f:
        current = 0.0
        for idx, (chunk, dur) in enumerate(zip(chunks, durations), 1):
            end = current + dur
            f.write(f"{idx}\n{fmt_time(current)} --> {fmt_time(end)}\n{chunk}\n\n")
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

    render_mode = "NVENC (GPU)" if use_gpu else "libx264 (CPU)"
    cb(5, f"Рендер: {render_mode} | {width}×{height} @ {config.fps}fps")
    if log:
        log.info(
            f"Video render START — {render_mode} | {width}×{height}@{config.fps}fps | "
            f"workers={config.parallel_workers} | gpu={config.use_gpu} | "
            f"output={config.output_path}"
        )

    cb(8, "Определяем длину аудио...")
    audio_dur       = get_audio_duration(config.audio_path)
    total_video_dur = audio_dur + config.extra_seconds

    cb(12, "Собираем исходные видеофайлы...")
    video_files = get_video_files(config.source_folder)
    if not video_files:
        raise RuntimeError(f"В папке '{config.source_folder}' нет видеофайлов.")

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
        clip_dur  = round(random.uniform(config.clip_min_dur, config.clip_max_dur), 2)
        max_start = max(0.0, src_dur - clip_dur - 0.5)
        start     = round(random.uniform(0, max_start), 2) if max_start > 0 else 0.0
        actual    = min(clip_dur, src_dur - start)
        clip_infos.append((src, start, actual))
        clips_needed -= actual

    cb(18, f"Нарезаем {len(clip_infos)} клипов параллельно ({config.parallel_workers} потока)...")
    if log:
        log.info(
            f"Cutting {len(clip_infos)} clips from {len(video_files)} sources "
            f"(audio={audio_dur:.1f}s, total_dur={total_video_dur:.1f}s)"
        )

    with tempfile.TemporaryDirectory(prefix="ytgen_") as tmpdir:
        clip_paths = [os.path.join(tmpdir, f"clip_{i:04d}.mp4")
                      for i in range(len(clip_infos))]

        done_count = 0
        # Clip FPS: match final output FPS so concat -c copy works without freezing
        clip_fps = min(config.fps, 60)
        with ThreadPoolExecutor(max_workers=config.parallel_workers) as ex:
            futures = {
                ex.submit(_cut_clip, use_gpu, src, start, dur, clip_paths[i],
                          clip_fps, width, height): i
                for i, (src, start, dur) in enumerate(clip_infos)
            }
            for fut in as_completed(futures):
                fut.result()
                done_count += 1
                pct = 18 + int(done_count / len(clip_infos) * 35)
                cb(pct, f"Клипов нарезано: {done_count}/{len(clip_infos)}")

        cb(55, "Склеиваем клипы...")
        if log:
            log.info(f"Concatenating {len(clip_paths)} clips...")
        concat_list = os.path.join(tmpdir, "concat.txt")
        _build_concat_list(clip_paths, concat_list)
        raw_video = os.path.join(tmpdir, "raw_concat.mp4")
        _concat_clips(concat_list, raw_video)
        if log:
            log.info("Concat done")

        # Subtitles (optional — skip if SRT generation fails)
        srt_path = None
        if config.script:
            cb(60, "Создаём субтитры...")
            try:
                srt_path = os.path.join(tmpdir, "subs.srt")
                _make_srt(config.script, audio_dur, srt_path)
                if log:
                    log.info("SRT subtitles generated")
            except Exception as srt_err:
                srt_path = None   # render without subtitles on error
                if log:
                    log.warning(f"SRT generation failed, rendering without subs: {srt_err}")

        render_label = "NVENC GPU" if use_gpu else "CPU ultrafast"
        render_duration = total_video_dur  # used for progress tracking
        cb(63, f"Финальный рендер ({render_label})...")
        if log:
            log.info(f"Final render start: {render_label}, duration={render_duration:.1f}s")
        os.makedirs(os.path.dirname(os.path.abspath(config.output_path)), exist_ok=True)

        bg_kw = dict(
            bg_music_path=config.bg_music_path,
            bg_music_volume=config.bg_music_volume,
        )

        if use_gpu:
            try:
                _final_render_gpu(
                    raw_video, config.audio_path, config.output_path,
                    width, height, config.fps,
                    config.noise_intensity, config.voice_volume,
                    srt_path, **bg_kw,
                    progress_cb=cb, total_duration=render_duration,
                )
            except Exception as e:
                err_short = str(e)[:120]
                cb(63, f"NVENC не сработал ({err_short}), переключаемся на CPU ultrafast...")
                if log:
                    log.error(f"NVENC render failed: {e}")
                use_gpu = False

        if not use_gpu:
            try:
                _final_render_cpu(
                    raw_video, config.audio_path, config.output_path,
                    width, height, config.fps,
                    config.noise_intensity, config.voice_volume,
                    srt_path, **bg_kw,
                    progress_cb=cb, total_duration=render_duration,
                )
            except Exception as cpu_err:
                if srt_path:
                    if log:
                        log.warning(f"CPU render with subs failed, retrying without subs: {cpu_err}")
                    cb(65, "Субтитры вызвали ошибку — рендер без субтитров...")
                    _final_render_cpu_no_subs(
                        raw_video, config.audio_path, config.output_path,
                        width, height, config.fps,
                        config.noise_intensity, config.voice_volume,
                        **bg_kw,
                        progress_cb=cb, total_duration=render_duration,
                    )
                else:
                    if log:
                        log.error(f"CPU render failed: {cpu_err}", exc_info=False)
                    raise

    cb(100, "Готово!")
    if log:
        log.info(f"Video render COMPLETE → {config.output_path}")
    return config.output_path
