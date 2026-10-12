"""전체 흐름: 대본 → 컷 계획 → 개인정보 탐지 → 자막 → 렌더링."""
import hashlib
import json
import shutil
import time
from pathlib import Path

from .config import Config
from .cutter import TimeMap, mark_fillers, plan_segments
from .media import energy_db, extract_audio, load_wav, probe
from .subtitles import apply_speech_pii, build_cues, place_words, style_metrics, write_ass, write_srt
from .transcribe import load_or_transcribe

ROOT = Path(__file__).resolve().parent.parent


def _fmt(t):
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:05.2f}"


def _prepare_font(workdir, cfg):
    fonts = workdir / "fonts"
    fonts.mkdir(exist_ok=True)
    if cfg.font_file and Path(cfg.font_file).exists():
        shutil.copy(cfg.font_file, fonts)
        try:
            from PIL import ImageFont
            return ImageFont.truetype(cfg.font_file, 10).getname()[0]
        except Exception:
            return cfg.font_name
    for f in ("malgunbd.ttf", "malgun.ttf"):
        src = Path("C:/Windows/Fonts") / f
        if src.exists():
            shutil.copy(src, fonts)
    return cfg.font_name


def process(src, cfg: Config = None, out_dir=None, log=print):
    cfg = cfg or Config()
    src = Path(src).resolve()
    out_dir = Path(out_dir or ROOT / "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    st = src.stat()
    tag = hashlib.md5(f"{src.name}{st.st_size}{st.st_mtime}".encode()).hexdigest()[:8]
    workdir = ROOT / "work" / f"{src.stem}_{tag}"
    workdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    info = probe(src)
    if not info.has_audio:
        raise RuntimeError("오디오가 없는 영상은 대본을 만들 수 없습니다.")
    log(f"▶ {src.name}  {info.width}x{info.height} {info.fps:.2f}fps  길이 {_fmt(info.duration)}")

    # 1. 대본
    log("① 음성 추출 · 대본 인식")
    wav = workdir / "audio16k.wav"
    if not wav.exists():
        extract_audio(src, wav)
    words = load_or_transcribe(wav, workdir / "transcript.json", cfg, log)
    if not words:
        raise RuntimeError("인식된 말소리가 없습니다.")
    db = energy_db(load_wav(wav))

    # 2. 컷 계획
    log("② 무음 · 필러 컷 계산")
    mark_fillers(words, cfg)
    segs, removed = plan_segments(words, db, info.duration, cfg)
    tm = TimeMap(segs)
    n_fill = sum(w["filler"] for w in words)
    silence_cut = sum(e - s for s, e, r in removed if r == "무음")
    filler_cut = sum(e - s for s, e, r in removed if r == "필러")
    log(f"  남길 구간 {len(segs)}개 · 무음 {silence_cut:.1f}s 제거 · 필러 {n_fill}개({filler_cut:.1f}s) 제거"
        f" → {_fmt(info.duration)} ⇒ {_fmt(tm.total)}")

    # 3. 화면 개인정보
    video_src = src
    pii_report = []
    if cfg.mosaic_text_pii or cfg.mosaic_faces:
        from .mosaic import render_mosaic, scan_text_pii
        dets = []
        if cfg.mosaic_text_pii:
            log("③ 화면 속 개인정보 검사 (OCR)")
            dets = scan_text_pii(src, info, tm, cfg, log)
            for t, hits in dets:
                for h in hits:
                    pii_report.append((t, h[4]))
            log(f"  개인정보로 보이는 텍스트 {len(pii_report)}건 (샘플 기준)")
        if pii_report or cfg.mosaic_faces:
            log("  모자이크 적용 중")
            video_src = workdir / "mosaic.mp4"
            render_mosaic(src, video_src, info, dets, cfg, log)

    # 4. 자막
    placed = place_words(words, tm)
    beeps, spoken = ([], [])
    if cfg.beep_spoken_pii:
        beeps, spoken = apply_speech_pii(placed)
        if spoken:
            log(f"  말로 나온 개인정보 {len(spoken)}건 → 삐 처리 · 자막 가림")
    ass_name = None
    stem = src.stem
    srt_path = out_dir / f"{stem}_자막.srt"
    if cfg.subtitles:
        log("④ 자막 생성")
        _, max_chars = style_metrics(info.width, info.height, cfg)
        cues = build_cues(placed, max_chars, cfg.max_cue_duration)
        write_srt(cues, srt_path)
        if cfg.burn_subtitles:
            font = _prepare_font(workdir, cfg)
            write_ass(cues, workdir / "subs.ass", info.width, info.height, cfg, font)
            ass_name = "subs.ass"
        log(f"  자막 {len(cues)}줄")

    # 5. 렌더링
    log("⑤ 최종 영상 렌더링")
    from .render import render_final
    out_path = out_dir / f"{stem}_편집본.mp4"
    render_final(video_src, src, segs, tm.total, beeps, ass_name, out_path, workdir, info, cfg)

    # 기록
    (workdir / "edit_plan.json").write_text(json.dumps({
        "source": str(src), "config": cfg.to_dict(), "keep": segs,
        "removed": removed, "beeps": beeps}, ensure_ascii=False, indent=1), encoding="utf-8")
    script = "".join(w["text"] for w in placed).strip()
    (out_dir / f"{stem}_대본.txt").write_text(script, encoding="utf-8")

    report = [
        f"원본: {src.name}",
        f"길이: {_fmt(info.duration)} → {_fmt(tm.total)}  ({info.duration - tm.total:.1f}초 단축)",
        f"컷: {len(removed)}곳 (무음 {sum(r == '무음' for *_, r in removed)} · 필러 포함 {sum(r == '필러' for *_, r in removed)})",
        f"제거된 필러 단어: {n_fill}개",
    ]
    if cfg.mosaic_text_pii:
        kinds = {}
        for t, k in pii_report:
            kinds.setdefault(k, []).append(t)
        if kinds:
            report.append("화면 개인정보 모자이크:")
            for k, ts in kinds.items():
                report.append(f"  - {k}: 원본 {_fmt(min(ts))} ~ {_fmt(max(ts))} 부근")
        else:
            report.append("화면 개인정보: 발견 안 됨")
    if spoken:
        report.append("음성 개인정보 삐 처리: " + ", ".join(f"{k}@{_fmt(t)}" for k, t in spoken))
    report.append(f"처리 시간: {time.time() - t0:.0f}초")
    report_path = out_dir / f"{stem}_리포트.txt"
    report_path.write_text("\n".join(report), encoding="utf-8")
    log("✔ 완료: " + str(out_path))
    return {"video": out_path, "srt": srt_path if cfg.subtitles else None,
            "report": report_path, "report_text": "\n".join(report)}
