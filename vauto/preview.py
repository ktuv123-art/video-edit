"""자막 위치 지정용 미리보기: 영상에서 한 장면을 뽑고, 그 위에 샘플 자막을 그려준다."""
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Config
from .media import probe, run
from .subtitles import clamp_center, style_metrics

SAMPLE = "여기에 자막이 표시됩니다"
_FONT = next((p for p in ("C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf") if Path(p).exists()), None)


def extract_frame(video, max_side=1280):
    """영상 앞쪽의 대표 장면 한 장을 PNG로 저장하고 경로를 돌려준다."""
    info = probe(video)
    t = 1.0 if info.duration > 3 else 0.0
    out = Path(tempfile.mkdtemp(prefix="vauto_prev_")) / "frame.png"
    scale = f"scale='if(gt(iw,ih),min({max_side},iw),-2)':'if(gt(iw,ih),-2,min({max_side},ih))'"
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t}", "-i", str(video), "-frames:v", "1", "-vf", scale, str(out)])
    return str(out)


def default_pos(img_w, img_h, cfg):
    fs, _ = style_metrics(img_w, img_h, cfg)
    return 0.5, 1 - cfg.sub_margin - fs * 0.6 / img_h


def render_preview(frame_path, pos, font_scale=1.0):
    """frame 위에 샘플 자막을 pos(비율)에 그린 이미지를 PIL로 돌려준다."""
    img = Image.open(frame_path).convert("RGB")
    W, H = img.size
    cfg = Config(font_scale=font_scale)
    fs, _ = style_metrics(W, H, cfg)
    px, py = pos if pos else default_pos(W, H, cfg)
    font = ImageFont.truetype(_FONT, fs) if _FONT else ImageFont.load_default()
    tw = font.getlength(SAMPLE)
    cx, cy = clamp_center(px * W, py * H, tw, fs, W, H)
    d = ImageDraw.Draw(img)
    d.text((cx, cy), SAMPLE, font=font, fill="white", anchor="mm",
           stroke_width=max(2, round(fs * 0.09)), stroke_fill="black")
    # 지정한 점 표시 (십자)
    r = max(6, W // 120)
    d.line([(cx - r, cy), (cx + r, cy)], fill="#ff3b30", width=2)
    d.line([(cx, cy - r), (cx, cy + r)], fill="#ff3b30", width=2)
    return img


def image_size(path):
    with Image.open(path) as im:
        return im.size
