from dataclasses import dataclass, field, asdict


@dataclass
class Config:
    # ── 음성 인식 ──────────────────────────────────────────
    whisper_model: str = "large-v3"      # large-v3 / large-v3-turbo / medium ...
    language: str = "ko"
    device: str = "auto"                 # auto / cuda / cpu

    # ── 컷 편집 ────────────────────────────────────────────
    cut_silence: bool = True
    cut_fillers: bool = True
    aggressive_fillers: bool = False     # "그", "저", "아", "뭐" 를 머뭇거릴 때만 제거
    max_pause: float = 0.40              # 이보다 짧은 쉼은 자연스러운 호흡으로 보고 유지(초)
    min_silence: float = 0.60            # 단어 구간 안에서도 이보다 긴 무음은 잘라냄(초)
    pad_before: float = 0.10             # 컷 앞쪽 여유(초)
    pad_after: float = 0.15              # 컷 뒤쪽 여유(초)
    fade: float = 0.012                  # 컷 지점 오디오 페이드(클릭음 방지)

    # ── 자막 ───────────────────────────────────────────────
    subtitles: bool = True
    burn_subtitles: bool = True
    max_chars: int = 0                   # 0 = 화면 비율에 맞춰 자동
    max_cue_duration: float = 4.0
    font_name: str = "Malgun Gothic"
    font_file: str = ""                  # 비워두면 맑은 고딕 Bold 사용
    font_scale: float = 1.0
    sub_margin: float = 0.08             # 화면 아래 여백(높이 대비)
    sub_pos: tuple = None                # 자막 중심 위치 (x, y) — 화면 비율 0~1. None = 아래 가운데

    # ── 개인정보 ───────────────────────────────────────────
    mosaic_text_pii: bool = True         # 화면 속 전화번호/주소 등 OCR 모자이크
    mosaic_faces: bool = False           # 모든 얼굴 모자이크(실험적)
    beep_spoken_pii: bool = True         # 말로 나온 전화번호 등 삐 처리 + 자막 마스킹
    ocr_interval: float = 0.5            # OCR 샘플 간격(초) — 화면이 많이 움직이면 줄이세요
    ocr_max_side: int = 1920
    ocr_min_conf: float = 0.30

    # ── 출력 ───────────────────────────────────────────────
    video_quality: int = 21              # 낮을수록 고화질 (CQ/CRF)

    def to_dict(self):
        return asdict(self)


FILLERS = {
    "어", "어어", "어어어", "음", "음음", "으음", "음…", "엄", "어음", "흠", "으", "으으",
    "에", "에에", "아아", "어으", "음으", "읍", "흐음",
}

# 머뭇거릴 때만 필러로 보는 단어 (뒤에 쉼이 있거나 길게 끌 때)
SOFT_FILLERS = {"그", "저", "아", "뭐", "그니까", "막"}
