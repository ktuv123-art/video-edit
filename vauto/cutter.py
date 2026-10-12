"""대본(단어 타임스탬프) + 오디오 에너지로 남길 구간을 계산한다."""
import re
from bisect import bisect_right

from .config import FILLERS, SOFT_FILLERS
from .media import detect_silences, snap_to_quiet

_FILLER_RE = re.compile(r"(어|음|으|엄|흠|에)+")


def mark_fillers(words, cfg):
    for i, w in enumerate(words):
        core = re.sub(r"[^가-힣]", "", w["text"])
        w["filler"] = False
        if not cfg.cut_fillers or not core:
            continue
        if core in FILLERS or _FILLER_RE.fullmatch(core):
            w["filler"] = True
        elif cfg.aggressive_fillers and core in SOFT_FILLERS:
            nxt = words[i + 1] if i + 1 < len(words) else None
            gap = (nxt["start"] - w["end"]) if nxt else 1.0
            if gap >= 0.3 or (w["end"] - w["start"]) >= 0.5:
                w["filler"] = True
    return words


def plan_segments(words, db, duration, cfg):
    """남길 구간 [(start, end)] 과 잘린 구간 [(start, end, 이유)] 반환."""
    fillers = [(w["start"], w["end"]) for w in words if w["filler"]]

    if not cfg.cut_silence:
        segs = _complement(fillers, duration, db) if fillers else [(0.0, duration)]
        return segs, _removed(segs, duration, fillers)

    silences, _ = detect_silences(db, cfg.min_silence)

    # 1) 필러가 아닌 단어들을 '자연스러운 쉼' 기준으로 묶는다. 필러가 끼면 거기서 끊는다.
    groups, prev_filler = [], True
    for w in words:
        if w["filler"]:
            prev_filler = True
            continue
        if groups and not prev_filler and w["start"] - groups[-1][1] <= cfg.max_pause:
            groups[-1][1] = max(groups[-1][1], w["end"])
        else:
            groups.append([w["start"], w["end"]])
        prev_filler = False

    # 2) 실제 오디오 무음으로 다듬기: 묶음 안의 긴 무음은 쪼개고, 가장자리 무음은 잘라낸다.
    refined = []
    for s, e in groups:
        for ss, se in silences:
            if se <= s or ss >= e:
                continue
            if ss <= s < se:            # 앞쪽이 무음 → 시작을 뒤로
                s = min(se, e)
            elif ss < e <= se:          # 뒤쪽이 무음 → 끝을 앞으로
                e = max(ss, s)
            elif s < ss and se < e:     # 중간의 긴 무음 → 분할
                refined.append([s, ss])
                s = se
        if e - s > 0.05:
            refined.append([s, e])
    groups = refined

    # 3) 앞뒤 여유를 주되, 필러나 이웃 구간을 침범하지 않게 하고, 가장 조용한 지점에 컷을 맞춘다.
    f_ends = sorted(fe for _, fe in fillers)
    f_starts = sorted(fs for fs, _ in fillers)
    out = []
    for i, (s, e) in enumerate(groups):
        prev_e = groups[i - 1][1] if i else 0.0
        next_s = groups[i + 1][0] if i + 1 < len(groups) else duration
        k = bisect_right(f_ends, s) - 1
        lo = max(prev_e, f_ends[k] if k >= 0 else 0.0, 0.0)
        k = bisect_right(f_starts, e)
        hi = min(next_s, f_starts[k] if k < len(f_starts) else duration, duration)

        ns = max(s - cfg.pad_before, lo)
        ne = min(e + cfg.pad_after, hi)
        ns = snap_to_quiet(db, ns, max(lo, ns - 0.04), min(s, ns + 0.04))
        ne = snap_to_quiet(db, ne, max(e, ne - 0.04), min(hi, ne + 0.04))
        if ne - ns >= 0.12:
            out.append([ns, ne])

    # 4) 거의 붙어있는 구간은 합친다 (불필요한 컷 방지)
    merged = []
    for s, e in out:
        if merged and s - merged[-1][1] < 0.06:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    segs = [(round(s, 3), round(e, 3)) for s, e in merged]
    return segs, _removed(segs, duration, fillers)


def _complement(fillers, duration, db):
    segs, t = [], 0.0
    for fs, fe in sorted(fillers):
        fs = snap_to_quiet(db, fs, fs - 0.04, fs + 0.02)
        fe = snap_to_quiet(db, fe, fe - 0.02, fe + 0.04)
        if fs - t > 0.05:
            segs.append((t, fs))
        t = max(t, fe)
    if duration - t > 0.05:
        segs.append((t, duration))
    return segs


def _removed(segs, duration, fillers):
    gaps, t = [], 0.0
    for s, e in segs:
        if s - t > 0.01:
            gaps.append((t, s))
        t = e
    if duration - t > 0.01:
        gaps.append((t, duration))
    out = []
    for gs, ge in gaps:
        has_filler = any(fs < ge and fe > gs for fs, fe in fillers)
        out.append((round(gs, 3), round(ge, 3), "필러" if has_filler else "무음"))
    return out


class TimeMap:
    """원본 시간 ↔ 편집본 시간 변환."""

    def __init__(self, segs):
        self.segs = segs
        self.starts = [s for s, _ in segs]
        self.offsets, acc = [], 0.0
        for s, e in segs:
            self.offsets.append(acc)
            acc += e - s
        self.total = acc

    def seg_index(self, t):
        i = bisect_right(self.starts, t) - 1
        if i >= 0 and t <= self.segs[i][1]:
            return i
        return None

    def to_new(self, t, side="nearest"):
        """원본 t → 편집본 시간. 잘린 구간이면 side에 따라 앞/뒤 구간 경계로 붙인다."""
        i = bisect_right(self.starts, t) - 1
        if i >= 0 and t <= self.segs[i][1]:
            return self.offsets[i] + (t - self.segs[i][0])
        if side == "before":     # 이전 구간의 끝
            return self.offsets[i] + (self.segs[i][1] - self.segs[i][0]) if i >= 0 else 0.0
        # 다음 구간의 시작
        j = i + 1
        return self.offsets[j] if j < len(self.segs) else self.total

    def range_to_new(self, a, b):
        """원본 [a,b] 중 남아있는 부분들을 편집본 시간 구간 목록으로."""
        out = []
        for (s, e), off in zip(self.segs, self.offsets):
            lo, hi = max(a, s), min(b, e)
            if hi > lo:
                out.append((off + lo - s, off + hi - s))
        return out
