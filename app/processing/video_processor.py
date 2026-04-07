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
    fps:            int   = 60
    bg_volume:      float = 0.05
    voice_volume:   float = 1.0
    noise_intensity: int  = 8
    clip_min_dur:   float = 3.0
    clip_max_dur:   float = 5.0
    extra_seconds:  float = 10.0
    script:         str   = ""
    subtitle_font_size: int = 32
    use_gpu:        bool  = True
    parallel_workers: int = 3
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
                  output_path: str, fps: int = 30):
    # Force constant frame rate so all clips have identical FPS for concat
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-vf", f"fps={fps}",
        "-c:v", "h264_nvenc", "-preset", "p1", "-rc", "constqp", "-qp", "28",
        "-an",
        "-video_track_timescale", "90000",
        output_path,
    ], f"cut_clip_gpu {os.path.basename(input_path)}")


def _cut_clip_cpu(input_path: str, start: float, duration: float,
                  output_path: str, fps: int = 30):
    # Force constant frame rate so all clips have identical FPS for concat
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-vf", f"fps={fps}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-an",
        "-video_track_timescale", "90000",
        output_path,
    ], f"cut_clip_cpu {os.path.basename(input_path)}")


def _cut_clip(use_gpu: bool, input_path: str, start: float,
              duration: float, output_path: str, fps: int = 30):
    if use_gpu and gpu_available():
        try:
            _cut_clip_gpu(input_path, start, duration, output_path, fps=fps)
            return
        except Exception:
            pass
    _cut_clip_cpu(input_path, start, duration, output_path, fps=fps)


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
        f"'FontSize=18,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
        f"Outline=2,Shadow=1,Alignment=2,MarginV=30'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Final render — GPU (NVENC)
# ─────────────────────────────────────────────────────────────────────────────

def _final_render_gpu(
    raw_video: str, audio_path: str, output_path: str,
    width: int, height: int, fps: int,
    noise: int, voice_volume: float,
    srt_path: Optional[str],
    progress_cb: Optional[Callable[[int, str], None]] = None,
    total_duration: float = 0.0,
):
    vf_parts = []
    if srt_path:
        vf_parts.append(_srt_filter(srt_path))
    if noise > 0:
        vf_parts.append(f"noise=alls={noise}:allf=t+u")
    vf_parts.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
    vf_parts.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    vf_parts.append(f"fps={fps}")
    vf = ",".join(vf_parts)

    # NOTE: do NOT use -hwaccel_output_format cuda here — it conflicts with
    # CPU-side filters (subtitles, noise). Use -hwaccel cuda for decode only;
    # frames are downloaded to RAM for filtering, then encoded with h264_nvenc.
    #
    # Tuned for GTX 1650 Ti (Lenovo Legion 5):
    #   p3 preset = good balance of speed/quality on this GPU tier
    #   cq 23 = good quality, faster than 20
    #   maxrate 8M = sufficient for 1080p YouTube (they re-encode anyway)
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-hwaccel", "cuda",
        "-i", raw_video, "-i", audio_path,
        "-vf", vf,
        "-map", "0:v", "-map", "1:a",
        "-af", f"volume={voice_volume:.4f}",
        "-c:v", "h264_nvenc",
        "-preset", "p3",        # p1=fastest … p7=slowest; p3 = good for GTX 1650 Ti
        "-tune", "hq",
        "-rc", "vbr", "-cq", "23", "-b:v", "0",
        "-maxrate:v", "8M" if height == 1080 else "4M",
        "-bufsize:v", "16M" if height == 1080 else "8M",
        "-profile:v", "high", "-level", "4.2",
        "-g", str(fps * 2),
        "-spatial-aq", "1",     # spatial AQ improves perceptual quality on GTX 1650 Ti
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ], "final_render_gpu", progress_cb=progress_cb,
       progress_start=63, progress_end=98, total_duration=total_duration)


# ─────────────────────────────────────────────────────────────────────────────
# Final render — CPU (libx264)
# ─────────────────────────────────────────────────────────────────────────────

def _final_render_cpu(
    raw_video: str, audio_path: str, output_path: str,
    width: int, height: int, fps: int,
    noise: int, voice_volume: float,
    srt_path: Optional[str],
    progress_cb: Optional[Callable[[int, str], None]] = None,
    total_duration: float = 0.0,
):
    vf_parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        f"fps={fps}",
    ]
    if noise > 0:
        vf_parts.append(f"noise=alls={noise}:allf=t+u")
    if srt_path:
        vf_parts.append(_srt_filter(srt_path))
    vf = ",".join(vf_parts)

    # i5-10300H: 4 cores / 8 threads — use all of them
    cpu_cores = os.cpu_count() or 8
    # ultrafast + tune fastdecode: optimal for i5-10300H CPU fallback
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-i", raw_video, "-i", audio_path,
        "-vf", vf,
        "-map", "0:v", "-map", "1:a",
        "-af", f"volume={voice_volume:.4f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-tune", "fastdecode",
        "-threads", str(cpu_cores),
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ], "final_render_cpu", progress_cb=progress_cb,
       progress_start=63, progress_end=98, total_duration=total_duration)


def _final_render_cpu_no_subs(
    raw_video: str, audio_path: str, output_path: str,
    width: int, height: int, fps: int,
    noise: int, voice_volume: float,
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

    cpu_cores = os.cpu_count() or 4
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-i", raw_video, "-i", audio_path,
        "-vf", vf,
        "-map", "0:v", "-map", "1:a",
        "-af", f"volume={voice_volume:.4f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-threads", str(cpu_cores),
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ], "final_render_cpu_no_subs", progress_cb=progress_cb,
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


def _split_into_chunks(text: str, max_chars: int = 42) -> list[str]:
    """Split text into lines of max_chars, max 2 lines per chunk."""
    words = text.split()
    chunks: list[str] = []
    line1, line2 = "", ""
    for word in words:
        # Try to add to line1
        test = (line1 + " " + word).strip() if line1 else word
        if len(test) <= max_chars:
            line1 = test
        else:
            # line1 is full — try line2
            test2 = (line2 + " " + word).strip() if line2 else word
            if len(test2) <= max_chars:
                line2 = test2
            else:
                # Both lines full — flush and start new chunk
                chunk = line1
                if line2:
                    chunk += "\n" + line2
                chunks.append(chunk)
                line1 = word
                line2 = ""
    # Flush remaining
    if line1 or line2:
        chunk = line1
        if line2:
            chunk += "\n" + line2
        chunks.append(chunk)
    return [c for c in chunks if c.strip()]


def _make_srt(script: str, audio_duration: float, output_path: str):
    clean = _clean_script_for_subs(script)
    # Split into short phrases by punctuation first
    sentences = re.split(r'(?<=[.!?,;])\s+', clean)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return

    # Break long sentences into 2-line chunks (max 42 chars/line)
    chunks: list[str] = []
    for sent in sentences:
        chunks.extend(_split_into_chunks(sent, max_chars=42))

    if not chunks:
        return

    total_chars = sum(len(c.replace("\n", " ")) for c in chunks) or 1

    def fmt_time(seconds: float) -> str:
        h  = int(seconds // 3600)
        m  = int((seconds % 3600) // 60)
        s  = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(output_path, "w", encoding="utf-8") as f:
        current = 0.0
        for idx, chunk in enumerate(chunks, 1):
            char_count = len(chunk.replace("\n", " "))
            duration   = (char_count / total_chars) * audio_duration
            end        = current + max(duration, 0.8)
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

    with tempfile.TemporaryDirectory(prefix="ytgen_") as tmpdir:
        clip_paths = [os.path.join(tmpdir, f"clip_{i:04d}.mp4")
                      for i in range(len(clip_infos))]

        done_count = 0
        # Clip FPS: match final output FPS so concat -c copy works without freezing
        clip_fps = min(config.fps, 60)
        with ThreadPoolExecutor(max_workers=config.parallel_workers) as ex:
            futures = {
                ex.submit(_cut_clip, use_gpu, src, start, dur, clip_paths[i], clip_fps): i
                for i, (src, start, dur) in enumerate(clip_infos)
            }
            for fut in as_completed(futures):
                fut.result()
                done_count += 1
                pct = 18 + int(done_count / len(clip_infos) * 35)
                cb(pct, f"Клипов нарезано: {done_count}/{len(clip_infos)}")

        cb(55, "Склеиваем клипы...")
        concat_list = os.path.join(tmpdir, "concat.txt")
        _build_concat_list(clip_paths, concat_list)
        raw_video = os.path.join(tmpdir, "raw_concat.mp4")
        _concat_clips(concat_list, raw_video)

        # Subtitles (optional — skip if SRT generation fails)
        srt_path = None
        if config.script:
            cb(60, "Создаём субтитры...")
            try:
                srt_path = os.path.join(tmpdir, "subs.srt")
                _make_srt(config.script, audio_dur, srt_path)
            except Exception:
                srt_path = None   # render without subtitles on error

        render_label = "NVENC GPU" if use_gpu else "CPU ultrafast"
        cb(63, f"Финальный рендер ({render_label})...")
        if log:
            log.info(f"Final render start: {render_label}, duration={render_duration:.1f}s")
        os.makedirs(os.path.dirname(os.path.abspath(config.output_path)), exist_ok=True)

        render_duration = total_video_dur  # used for progress tracking

        if use_gpu:
            try:
                _final_render_gpu(
                    raw_video, config.audio_path, config.output_path,
                    width, height, config.fps,
                    config.noise_intensity, config.voice_volume,
                    srt_path,
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
                    srt_path,
                    progress_cb=cb, total_duration=render_duration,
                )
            except Exception:
                if srt_path:
                    cb(65, "Субтитры вызвали ошибку — рендер без субтитров...")
                    _final_render_cpu_no_subs(
                        raw_video, config.audio_path, config.output_path,
                        width, height, config.fps,
                        config.noise_intensity, config.voice_volume,
                        progress_cb=cb, total_duration=render_duration,
                    )
                else:
                    raise

    cb(100, "Готово!")
    if log:
        log.info(f"Video render COMPLETE → {config.output_path}")
    return config.output_path
