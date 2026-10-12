"""컷 편집된 타임라인에 맞춘 자막 생성 (SRT + 화면 burn-in용 ASS)."""
import re

from .pii import find_pii

_END_PUNCT = re.compile(r"[.?!。？！]$")


def place_words(words, tm):
    """필러가 아닌 단어를 편집본 시간으로 옮긴다. 완전히 잘려나간 단어는 제외."""
    out = []
    for w in words:
        if w["filler"]:
            continue
        parts = tm.range_to_new(w["start"], w["end"])
        if not parts:
            continue
        out.append({**w, "ns": parts[0][0], "ne": parts[-1][1], "si": tm.seg_index(w["start"])})
    return out


def apply_speech_pii(placed):
    """말로 나온 개인정보: 자막은 *로 가리고, 삐 처리할 편집본 시간 구간을 돌려준다."""
    text, spans = "", []
    for w in placed:
        spans.append((len(text), len(text) + len(w["text"])))
        text += w["text"]
    hits = find_pii(text, speech=True)
    if not hits:
        return [], []
    chars = list(text)
    beeps, found = [], []
    for s, e, kind in hits:
        for c in range(s, e):
            if chars[c].isalnum():
                chars[c] = "*"
        idx = [i for i, (a, b) in enumerate(spans) if a < e and b > s]
        beeps.append((placed[idx[0]]["ns"], placed[idx[-1]]["ne"]))
        found.append((kind, placed[idx[0]]["ns"]))
    for i, (a, b) in enumerate(spans):
        placed[i]["text"] = "".join(chars[a:b])
    return beeps, found


def build_cues(placed, max_chars, max_dur):
    cues, cur = [], []

    def flush():
        if cur:
            t = "".join(w["text"] for w in cur).strip()
            t = re.sub(r"\s+", " ", t)
            t = re.sub(r"[.,。、]+$", "", t)
            if t:
                cues.append({"start": cur[0]["ns"], "end": cur[-1]["ne"], "text": t})
            cur.clear()

    for w in placed:
        if cur:
            last = cur[-1]
            cand = "".join(x["text"] for x in cur + [w]).strip()
            n = len("".join(x["text"] for x in cur).strip())
            # 띄어쓰기 없이 이어지는 조각(예: "-5678입니다")은 앞 단어와 떼지 않는다
            glued = not w["text"].startswith(" ") and len(cand) <= max_chars * 1.5
            if glued:
                pass
            elif (len(cand) > max_chars
                    or w["ne"] - cur[0]["ns"] > max_dur
                    or _END_PUNCT.search(last["text"].strip())
                    or (w["seg"] != last["seg"] and n >= max_chars * 0.3)
                    or (w["si"] != last["si"] and n >= max_chars * 0.5)):
                flush()
        cur.append(w)
    flush()

    # 타이밍 다듬기: 짧은 틈은 이어붙이고, 너무 짧은 자막은 늘린다
    for i, c in enumerate(cues):
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else None
        end = c["end"] + 0.15
        if nxt is not None:
            end = nxt if nxt - c["end"] < 0.4 else min(end, nxt)
        if end - c["start"] < 0.5:
            end = c["start"] + 0.5 if nxt is None else min(c["start"] + 0.5, max(nxt, end))
        c["end"] = end
    return cues


def _ts_srt(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _ts_ass(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def write_srt(cues, path):
    lines = []
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{_ts_srt(c['start'])} --> {_ts_srt(c['end'])}", c["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8-sig")


def style_metrics(width, height, cfg):
    fs = round(min(width, height) * 0.065 * cfg.font_scale)
    max_chars = cfg.max_chars or max(8, int(width * 0.88 / (fs * 0.95)))
    return fs, max_chars


def write_ass(cues, path, width, height, cfg, font_name):
    fs, _ = style_metrics(width, height, cfg)
    outline = max(2, round(fs * 0.09))
    margin_v = round(height * cfg.sub_margin)
    margin_lr = round(width * 0.05)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},{max(1, outline // 3)},2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = []
    for c in cues:
        t = c["text"].replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", "\\N")
        rows.append(f"Dialogue: 0,{_ts_ass(c['start'])},{_ts_ass(c['end'])},Default,,0,0,0,,{t}")
    path.write_text(head + "\n".join(rows) + "\n", encoding="utf-8-sig")
