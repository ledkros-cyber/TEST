"""
FFmpeg video processing pipeline — optimised for Lenovo Legion (NVIDIA RTX).

GPU pipeline (when NVENC available):
  Decode  → h264_cuvid (CUDA)
  Scale   → scale_cuda / scale_npp
  Encode  → h264_nvenc  preset p4 (quality) or p1 (speed)
  Clip cut→ parallel ThreadPoolExecutor (3 workers max)

Scene detection:
  Uses FFmpeg built-in scene filter — no extra dependencies needed.
  Results cached as <video>.scenes.json next to each source file.
  When enabled, clips are selected from detected exercise scenes and
  distributed across DIFFERENT source video files for maximum variety.

CPU fallback:
  libx264 preset ultrafast/fast
"""
import glob as glob_module
import json
import os
import random
import re
import subprocess
import tempfile
import textwrap
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional


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
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
        )
        return "h264_nvenc" in r.stdout
    except Exception:
        return False


def _probe_cuvid() -> bool:
    try:
        r = subprocess.run(
            [FFMPEG, "-hide_banner", "-hwaccels"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
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
        return "NVIDIA NVENC + CUDA (hardware render)"
    if nvenc:
        return "NVIDIA NVENC (hardware render, CPU decode)"
    return "CPU only (libx264)"


# ─────────────────────────────────────────────────────────────────────────────
# Config dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VideoConfig:
    source_folder:    str
    audio_path:       str
    output_path:      str
    quality:          str   = "1080p"
    fps:              int   = 60
    bg_volume:        float = 0.05
    voice_volume:     float = 1.0
    noise_intensity:  int   = 8
    clip_min_dur:     float = 3.0
    clip_max_dur:     float = 8.0
    extra_seconds:    float = 10.0
    script:           str   = ""
    subtitle_font_size: int = 32
    use_gpu:          bool  = True
    parallel_workers: int   = 3
    use_scene_detect: bool  = True   # detect exercise start/end per video
    scene_threshold:  float = 0.35   # FFmpeg scene change sensitivity (0.1–0.5)
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
        encoding="utf-8",
        errors="replace",
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
    return list(set(files))


# ─────────────────────────────────────────────────────────────────────────────
# Scene detection  (exercise start/end detection per video file)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_scenes_ffmpeg(
    video_path: str,
    threshold: float = 0.35,
    min_scene_len: float = 2.0,
) -> list[tuple[float, float]]:
    """
    Detect scene changes using FFmpeg built-in scene filter.
    Returns list of (start_sec, end_sec) pairs for each detected scene.
    Each scene corresponds to one exercise / activity segment.
    """
    try:
        duration = _get_video_duration(video_path)
    except Exception:
        return []

    try:
        cmd = [
            FFMPEG, "-i", video_path,
            "-vf", f"select=gt(scene\\,{threshold}),showinfo",
            "-vsync", "vfr",
            "-f", "null", "-",
        ]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=120, encoding="utf-8", errors="replace",
        )

        timestamps = [0.0]
        for line in result.stderr.split("\n"):
            if "pts_time:" in line:
                m = re.search(r"pts_time:([0-9.]+)", line)
                if m:
                    t = float(m.group(1))
                    if t > 0.5:
                        timestamps.append(t)
        timestamps.append(duration)
        timestamps = sorted(set(timestamps))

        scenes: list[tuple[float, float]] = []
        for i in range(len(timestamps) - 1):
            start = timestamps[i]
            end   = timestamps[i + 1]
            if end - start >= min_scene_len:
                scenes.append((start, end))

        if len(scenes) < 2:
            # Fallback: divide video into equal 30-60 sec segments
            scenes = _split_into_segments(duration)

        return scenes
    except Exception:
        try:
            duration = _get_video_duration(video_path)
            return _split_into_segments(duration)
        except Exception:
            return []


def _split_into_segments(
    duration: float,
    seg_duration: float = 40.0,
    min_seg: float = 2.0,
) -> list[tuple[float, float]]:
    """Divide a video into equal-length segments as fallback."""
    if duration < min_seg:
        return [(0.0, duration)]
    n = max(1, int(duration / seg_duration))
    step = duration / n
    return [(i * step, (i + 1) * step) for i in range(n)]


def get_scenes_cached(
    video_path: str,
    threshold: float = 0.35,
) -> list[tuple[float, float]]:
    """
    Return detected scenes for a video, using a JSON cache file.
    Cache file: <video_path>.scenes.json
    Delete cache file to force re-detection.
    """
    cache_path = video_path + ".scenes.json"

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            scenes = [tuple(pair) for pair in data.get("scenes", [])]
            if scenes:
                return scenes
        except Exception:
            pass

    scenes = _detect_scenes_ffmpeg(video_path, threshold=threshold)

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"scenes": scenes, "threshold": threshold}, f)
    except Exception:
        pass

    return scenes


def clear_scene_cache(folder: str):
    """Delete all cached scene files in a folder."""
    for cache_file in glob_module.glob(os.path.join(folder, "*.scenes.json")):
        try:
            os.remove(cache_file)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Clip pool builder  (round-robin across source files for uniqueness)
# ─────────────────────────────────────────────────────────────────────────────

def _build_clip_pool(
    video_files: list[str],
    use_scene_detect: bool,
    threshold: float,
    cb: Callable,
) -> list[tuple[str, float, float]]:
    """
    Build a pool of (video_path, scene_start, scene_end) from all source videos.
    When use_scene_detect=True, uses actual detected scenes.
    Otherwise, treats each video as one big scene.
    """
    pool: list[tuple[str, float, float]] = []

    for i, vpath in enumerate(video_files):
        try:
            if use_scene_detect:
                cb(0, f"Detecting scenes: {os.path.basename(vpath)} ({i+1}/{len(video_files)})")
                scenes = get_scenes_cached(vpath, threshold=threshold)
            else:
                dur = _get_video_duration(vpath)
                scenes = [(0.0, dur)]

            for start, end in scenes:
                if end - start >= 1.5:
                    pool.append((vpath, start, end))
        except Exception:
            continue

    return pool


def _select_clips_from_pool(
    pool: list[tuple[str, float, float]],
    clip_min_dur: float,
    clip_max_dur: float,
    total_needed: float,
) -> list[tuple[str, float, float]]:
    """
    Select clips from the pool until total_needed seconds are covered.
    Distributes selections across DIFFERENT source files for variety.
    Uses round-robin: never pick from the same file twice in a row.
    """
    if not pool:
        return []

    # Group pool by video file
    by_file: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    for entry in pool:
        by_file[entry[0]].append(entry)

    # Shuffle scenes within each file
    for scenes in by_file.values():
        random.shuffle(scenes)

    # Build file rotation list
    file_list = list(by_file.keys())
    random.shuffle(file_list)

    selected: list[tuple[str, float, float]] = []
    remaining = total_needed
    file_idx = 0
    attempts = 0
    max_attempts = len(pool) * 3 + 100

    while remaining > 0 and attempts < max_attempts:
        attempts += 1

        # Round-robin: pick next file that still has unused scenes
        orig_idx = file_idx
        chosen_file = None
        for _ in range(len(file_list)):
            f = file_list[file_idx % len(file_list)]
            file_idx += 1
            if by_file[f]:
                chosen_file = f
                break

        if chosen_file is None:
            # All scenes used — refill pool from scratch with fresh shuffle
            for f in file_list:
                scenes = [e for e in pool if e[0] == f]
                random.shuffle(scenes)
                by_file[f] = scenes
            file_idx = random.randint(0, len(file_list) - 1)
            continue

        # Pick a random scene from the chosen file
        scene_entry = by_file[chosen_file].pop(random.randrange(len(by_file[chosen_file])))
        _, scene_start, scene_end = scene_entry
        scene_dur = scene_end - scene_start

        # Clip is a sub-segment of the scene
        clip_dur = min(
            round(random.uniform(clip_min_dur, clip_max_dur), 2),
            scene_dur,
        )
        if clip_dur < 1.0:
            continue

        max_offset = max(0.0, scene_dur - clip_dur)
        offset = round(random.uniform(0, max_offset), 2)
        start  = scene_start + offset

        selected.append((chosen_file, start, clip_dur))
        remaining -= clip_dur

    return selected


# ─────────────────────────────────────────────────────────────────────────────
# Clip cutting  (GPU-accelerated when available)
# ─────────────────────────────────────────────────────────────────────────────

def _cut_clip_gpu(input_path: str, start: float, duration: float, output_path: str):
    cmd = [
        FFMPEG, "-y",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "h264_nvenc",
        "-preset", "p1",
        "-rc", "constqp",
        "-qp", "28",
        "-an",
        output_path,
    ]
    _run(cmd, f"cut_clip_gpu {os.path.basename(input_path)}")


def _cut_clip_cpu(input_path: str, start: float, duration: float, output_path: str):
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
            pass
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
        "-c:v", "h264_nvenc",
        "-preset", "p4",
        "-tune", "hq",
        "-rc", "vbr",
        "-cq", "20",
        "-b:v", "0",
        "-maxrate:v", "12M" if height == 1080 else "6M",
        "-bufsize:v", "24M" if height == 1080 else "12M",
        "-profile:v", "high",
        "-level", "4.2",
        "-g", str(fps * 2),
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

    cb(5, f"Render: {'NVENC (GPU)' if use_gpu else 'libx264 (CPU)'} | "
         f"{width}×{height} @ {config.fps}fps")

    cb(8, "Getting audio duration...")
    audio_dur       = get_audio_duration(config.audio_path)
    total_video_dur = audio_dur + config.extra_seconds

    cb(12, "Scanning source video files...")
    video_files = get_video_files(config.source_folder)
    if not video_files:
        raise RuntimeError(f"No video files found in '{config.source_folder}'.")

    random.shuffle(video_files)

    # ── Scene detection & clip pool ─────────────────────────────────────────
    if config.use_scene_detect:
        cb(15, f"Detecting exercise scenes in {len(video_files)} video files...")
        pool = _build_clip_pool(
            video_files, True, config.scene_threshold, cb
        )
        cb(22, f"Scene pool: {len(pool)} exercise segments across {len(video_files)} files")
    else:
        pool = _build_clip_pool(video_files, False, config.scene_threshold, cb)
        cb(22, f"Using {len(pool)} video segments (scene detection off)")

    if not pool:
        raise RuntimeError("Could not build clip pool — check video files.")

    # ── Select clips with round-robin diversity ──────────────────────────────
    cb(25, "Selecting clips from different source videos...")
    clip_infos = _select_clips_from_pool(
        pool,
        config.clip_min_dur,
        config.clip_max_dur,
        total_video_dur,
    )

    if not clip_infos:
        raise RuntimeError("Failed to select clips.")

    # Count unique source files used
    unique_sources = len(set(src for src, _, _ in clip_infos))
    cb(28, f"Selected {len(clip_infos)} clips from {unique_sources} different source files")

    with tempfile.TemporaryDirectory(prefix="ytgen_") as tmpdir:
        clip_paths = [
            os.path.join(tmpdir, f"clip_{i:04d}.mp4")
            for i in range(len(clip_infos))
        ]

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
                fut.result()
                done_count += 1
                pct = 28 + int(done_count / len(clip_infos) * 30)
                cb(pct, f"Clips cut: {done_count}/{len(clip_infos)}")

        # ── Concat ──────────────────────────────────────────────────────────
        cb(60, "Concatenating clips...")
        concat_list = os.path.join(tmpdir, "concat.txt")
        _build_concat_list(clip_paths, concat_list)
        raw_video = os.path.join(tmpdir, "raw_concat.mp4")
        _concat_clips(concat_list, raw_video)

        # ── Subtitles ────────────────────────────────────────────────────────
        srt_path = None
        if config.script:
            cb(62, "Generating subtitles...")
            srt_path = os.path.join(tmpdir, "subs.srt")
            _make_srt(config.script, audio_dur, srt_path)

        # ── Final render ─────────────────────────────────────────────────────
        cb(65, f"Final render {'(NVENC GPU)' if use_gpu else '(CPU)'}...")
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
                cb(65, f"NVENC failed ({e}), switching to CPU...")
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

    cb(100, "Done!")
    return config.output_path
