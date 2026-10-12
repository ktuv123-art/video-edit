"""ffmpeg/ffprobe 래퍼와 오디오 에너지 분석."""
import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

SR = 16000
HOP = 0.01  # 에너지 엔벨로프 해상도(초)

_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


def run(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, creationflags=_NO_WINDOW)
    if check and p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace")[-3000:]
        raise RuntimeError(f"명령 실패: {' '.join(map(str, cmd[:6]))} ...\n{err}")
    return p


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    fps_str: str
    duration: float
    has_audio: bool


def probe(path) -> VideoInfo:
    out = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]).stdout
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise RuntimeError("영상 스트림이 없습니다.")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])

    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    rot = int(v.get("tags", {}).get("rotate", rot))
    if abs(rot) % 180 == 90:
        w, h = h, w

    rate = v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1"
    try:
        fr = Fraction(rate)
        if fr <= 0 or fr > 240:
            raise ValueError
    except (ValueError, ZeroDivisionError):
        fr = Fraction(30, 1)
    # 흔한 프레임레이트로 정규화 (VFR 폰 영상 대비)
    stds = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
            Fraction(50), Fraction(60000, 1001), Fraction(60)]
    best = min(stds, key=lambda s: abs(float(fr) - float(s)))
    fr = best if abs(float(fr) - float(best)) < 0.15 else Fraction(round(float(fr)), 1)

    duration = float(data["format"].get("duration") or v.get("duration") or 0)
    return VideoInfo(w, h, float(fr), f"{fr.numerator}/{fr.denominator}", duration, has_audio)


def extract_audio(src, wav_path):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(SR),
         "-c:a", "pcm_s16le", str(wav_path)])


def load_wav(wav_path) -> np.ndarray:
    raw = Path(wav_path).read_bytes()
    # 표준 44바이트 헤더 대신 data 청크를 찾아서 읽는다
    idx = raw.find(b"data")
    pcm = np.frombuffer(raw[idx + 8:], dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def energy_db(audio: np.ndarray) -> np.ndarray:
    """10ms 단위 RMS(dB)."""
    hop = int(SR * HOP)
    win = hop * 3
    n = max(1, (len(audio) - win) // hop + 1)
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = audio[np.clip(idx, 0, len(audio) - 1)]
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def detect_silences(db: np.ndarray, min_len: float):
    """영상 자체의 소음 바닥/말소리 크기에 맞춰 적응형 임계값으로 무음 구간을 찾는다."""
    floor = np.percentile(db, 10)
    speech = np.percentile(db, 90)
    thr = floor + 0.30 * (speech - floor)
    thr = min(thr, speech - 18)  # 말소리가 아주 작아도 너무 공격적으로 자르지 않게
    quiet = db < thr
    silences = []
    i, n = 0, len(quiet)
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if (j - i) * HOP >= min_len:
                silences.append((i * HOP, j * HOP))
            i = j
        else:
            i += 1
    return silences, thr


def snap_to_quiet(db: np.ndarray, t: float, lo: float, hi: float) -> float:
    """t 주변 [lo, hi] 안에서 가장 조용한 지점으로 컷 위치를 옮긴다."""
    a, b = max(0, int(lo / HOP)), min(len(db) - 1, int(hi / HOP))
    if b <= a:
        return t
    k = a + int(np.argmin(db[a:b + 1]))
    return k * HOP


_ENCODER = None


def pick_encoder(quality: int):
    """NVENC가 되면 GPU 인코딩, 아니면 libx264."""
    global _ENCODER
    if _ENCODER is None:
        p = run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
                 "-c:v", "h264_nvenc", "-f", "null", "-"], check=False)
        _ENCODER = "nvenc" if p.returncode == 0 else "x264"
    if _ENCODER == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(quality), "-b:v", "0",
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(quality), "-pix_fmt", "yuv420p"]
