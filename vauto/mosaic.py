"""화면 속 개인정보(OCR) 탐지와 모자이크 렌더링."""
import subprocess

import cv2
import numpy as np

from .media import pick_encoder
from .pii import find_pii, is_label, label_has_value, normalize_ocr

_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


def _reader():
    import easyocr
    import torch
    return easyocr.Reader(["ko", "en"], gpu=torch.cuda.is_available(), verbose=False)


def _decode(src, vf, w, h):
    cmd = ["ffmpeg", "-v", "error", "-i", str(src), "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW,
                         bufsize=w * h * 3 * 2)
    size = w * h * 3
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        p.stdout.close()
        p.wait()


def _lines(items):
    """OCR 박스를 줄 단위로 묶는다."""
    items = sorted(items, key=lambda it: (it["box"][1] + it["box"][3]) / 2)
    lines = []
    for it in items:
        cy = (it["box"][1] + it["box"][3]) / 2
        hh = it["box"][3] - it["box"][1]
        if lines:
            ln = lines[-1]
            lcy = np.mean([(x["box"][1] + x["box"][3]) / 2 for x in ln])
            if abs(cy - lcy) < 0.5 * hh:
                ln.append(it)
                continue
        lines.append([it])
    return [sorted(ln, key=lambda it: it["box"][0]) for ln in lines]


def _pii_boxes(results, min_conf):
    items = []
    for pts, text, conf in results:
        if conf < min_conf or not text.strip():
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        items.append({"box": [min(xs), min(ys), max(xs), max(ys)], "text": text})
    hits = []
    for ln in _lines(items):
        joined, spans = "", []
        for it in ln:
            t = normalize_ocr(it["text"])
            if joined:
                joined += " "
            spans.append((len(joined), len(joined) + len(t)))
            joined += t
        marked = {}
        for s, e, kind in find_pii(joined):
            idx = [i for i, (a, b) in enumerate(spans) if a < e and b > s]
            if kind == "이메일*" and idx and idx[0] > 0:
                idx.insert(0, idx[0] - 1)     # 도메인만 잡혔으면 왼쪽의 아이디 부분도 가린다
            for i in idx:
                marked[i] = kind.rstrip("*")
        for i, it in enumerate(ln):
            if is_label(it["text"]):
                if label_has_value(it["text"]):
                    marked[i] = "라벨값"
                for j in range(i + 1, len(ln)):   # 라벨 오른쪽 값들
                    marked.setdefault(j, "라벨값")
        hits += [ln[i]["box"] + [kind] for i, kind in marked.items()]
    return hits


def scan_text_pii(src, info, tm, cfg, log=print):
    """일정 간격으로 프레임을 OCR → [(t, [[x1,y1,x2,y2,kind], ...]), ...] (원본 해상도 좌표)."""
    scale = min(1.0, cfg.ocr_max_side / max(info.width, info.height))
    w, h = int(info.width * scale) // 2 * 2, int(info.height * scale) // 2 * 2
    sx, sy = info.width / w, info.height / h
    vf = f"fps=1/{cfg.ocr_interval},scale={w}:{h}"
    reader = _reader()
    total = int(info.duration / cfg.ocr_interval) + 1
    dets, prev_thumb, prev_hits, ocr_count = [], None, [], 0
    for k, frame in enumerate(_decode(src, vf, w, h)):
        t = k * cfg.ocr_interval
        # 편집 후 남는 구간 근처만 검사
        if not tm.range_to_new(t - cfg.ocr_interval, t + cfg.ocr_interval):
            dets.append((t, []))
            continue
        thumb = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA)
        if prev_thumb is not None and np.mean(cv2.absdiff(thumb, prev_thumb)) < 1.5:
            hits = prev_hits                       # 화면 변화가 거의 없으면 이전 결과 재사용
        else:
            hits = _pii_boxes(reader.readtext(frame), cfg.ocr_min_conf)
            hits = [[b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy, b[4]] for b in hits]
            prev_thumb, prev_hits = thumb, hits
            ocr_count += 1
        dets.append((t, hits))
        if k % 20 == 0:
            log(f"  화면 개인정보 검사 {min(k, total)}/{total} (OCR {ocr_count}회)")
    return dets


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0


def _boxes_at(t, dets, interval):
    """두 샘플 사이 프레임: 매칭되는 박스는 보간, 아니면 양쪽 박스를 모두 가린다(누락 방지)."""
    k = int(t // interval)
    a = dets[k][1] if 0 <= k < len(dets) else []
    b = dets[k + 1][1] if 0 <= k + 1 < len(dets) else []
    if not a and not b:
        return []
    alpha = (t - k * interval) / interval
    out, used = [], set()
    for ba in a:
        best, bi = 0, -1
        for j, bb in enumerate(b):
            v = _iou(ba, bb)
            if v > best:
                best, bi = v, j
        if best > 0.2:
            used.add(bi)
            bb = b[bi]
            out.append([ba[i] + (bb[i] - ba[i]) * alpha for i in range(4)])
        else:
            out.append(ba[:4])
    out += [bb[:4] for j, bb in enumerate(b) if j not in used]
    return out


def _pixelate(img, box, W, H):
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    pad = 0.15 * max(bh, 1) + 6
    x1, y1 = int(max(0, x1 - pad)), int(max(0, y1 - pad))
    x2, y2 = int(min(W, x2 + pad)), int(min(H, y2 + pad))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    roi = img[y1:y2, x1:x2]
    cell = max(8, int((y2 - y1) / 3))
    small = cv2.resize(roi, (max(1, (x2 - x1) // cell), max(1, (y2 - y1) // cell)), interpolation=cv2.INTER_AREA)
    mosaic = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
    img[y1:y2, x1:x2] = cv2.GaussianBlur(mosaic, (0, 0), max(1, cell / 4))


def render_mosaic(src, out_path, info, dets, cfg, log=print):
    """원본에 모자이크를 입힌 중간 영상(무음) 생성. 프레임레이트는 고정(CFR)으로 맞춘다."""
    W, H, fps = info.width, info.height, info.fps
    face = None
    if cfg.mosaic_faces:
        face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    fscale = min(1.0, 640 / max(W, H))
    face_hist = []

    enc = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", info.fps_str, "-i", "-", *pick_encoder(14), str(out_path)]
    p = subprocess.Popen(enc, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    total = int(info.duration * fps)
    try:
        for i, frame in enumerate(_decode(src, f"fps={info.fps_str}", W, H)):
            t = i / fps
            boxes = _boxes_at(t, dets, cfg.ocr_interval) if dets else []
            if face is not None:
                small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None, fx=fscale, fy=fscale)
                found = face.detectMultiScale(small, 1.1, 6, minSize=(20, 20))
                face_hist.append([[x / fscale, y / fscale, (x + fw) / fscale, (y + fh) / fscale]
                                  for x, y, fw, fh in found])
                face_hist = face_hist[-6:]          # 최근 몇 프레임 유지 → 깜빡임 방지
                boxes = boxes + [b for fs in face_hist for b in fs]
            if boxes:
                frame = frame.copy()
                for b in boxes:
                    _pixelate(frame, b, W, H)
            p.stdin.write(frame.tobytes())
            if i % 300 == 0:
                log(f"  모자이크 적용 {i}/{total} 프레임")
        p.stdin.close()
    except BrokenPipeError:
        pass
    if p.wait() != 0:
        raise RuntimeError("모자이크 인코딩 실패: " + p.stderr.read().decode("utf-8", "replace")[-2000:])
