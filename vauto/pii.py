"""개인정보 패턴 탐지 (화면 OCR 텍스트·음성 대본 공용)."""
import re

_PLATE_CHARS = "가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주아바사자배하허호육해공국합"

# (종류, 정규식, 음성 대본에도 적용할지)
PATTERNS = [
    ("주민등록번호", r"(?<!\d)\d{6}\s?[-–]\s?[1-8][\d*]{6}(?!\d)", True),
    ("카드번호", r"(?<!\d)\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{3,4}(?!\d)", True),
    ("전화번호", r"(?<!\d)(?:\+82[-\s]?|0)1[016789][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)", True),
    ("전화번호", r"(?<!\d)0(?:2|[3-6][1-5]|70)[-.)\s]\s?\d{3,4}[-.\s]\d{4}(?!\d)", True),
    ("이메일", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}", True),
    ("계좌번호", r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,7}(?:-\d{1,3})?(?!\d)", True),
    ("여권번호", r"(?<![A-Za-z0-9])[MSRODG]\d{3}[A-Z]?\d{4,5}(?!\d)", False),
    ("차량번호", rf"(?<!\d)\d{{2,3}}\s?[{_PLATE_CHARS}]\s?\d{{4}}(?!\d)", False),
    ("주소", r"[가-힣]{2,}(?:로|길)\s?\d{1,4}(?:-\d{1,4})?(?:번길\s?\d{1,4})?(?!\d)", False),
    ("주소", r"[가-힣]{1,}동\s?\d{1,4}-\d{1,4}(?!\d)", False),
    ("주소", r"(?<!\d)\d{1,4}\s?동\s?\d{1,4}\s?호", False),
    ("주소", r"[가-힣]+(?:특별시|광역시|특별자치시|도)\s?[가-힣]+(?:시|군|구)", False),
    # OCR이 '@'나 '.com'을 잘못 읽은 이메일 (예: "hong©naver,com", "gildong 'example; cor")
    ("이메일*", r"[A-Za-z0-9._-]{2,}\s?[©®&]\s?[A-Za-z0-9-]{2,}", False),
    ("이메일*", r"(?i)(gmail|naver|daum|hanmail|kakao|nate|hotmail|outlook|icloud|yahoo|example)"
               r"[\W_]{0,3}\s*(com?|net|kr|cor|c0m)\b", False),
    # 말로 읽은 전화번호: "공일공 일이삼사 오육칠팔"
    ("전화번호", r"공\s?일\s?[공영일육칠팔구](?:\s?[공영일이삼사오육칠팔구]){7,8}", True),
]
_COMPILED = [(k, re.compile(p), sp) for k, p, sp in PATTERNS]

# 이 라벨 뒤에 오는 값은 개인정보로 간주 (택배 송장, 신분증, 서류 등)
LABEL_RE = re.compile(
    r"^\s*(이름|성명|성함|주소|연락처|전화번호|전화|휴대폰|핸드폰|휴대전화|생년월일|주민번호|주민등록번호|"
    r"계좌번호|계좌|이메일|e-?mail|받는\s?분|보내는\s?분|수령인|수취인|받는\s?사람|보내는\s?사람|운송장번호|송장번호)"
    r"\s*[:：]?\s*", re.IGNORECASE)


def _digits(s):
    return sum(c.isdigit() for c in s)


def find_pii(text, speech=False):
    """[(start, end, kind)] — 겹치는 매치는 먼저/길게 잡힌 것 우선."""
    hits = []
    for kind, rx, for_speech in _COMPILED:
        if speech and not for_speech:
            continue
        for m in rx.finditer(text):
            s = m.group(0)
            if kind == "계좌번호" and not (10 <= _digits(s) <= 14):
                continue
            hits.append((m.start(), m.end(), kind))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    out = []
    for h in hits:
        if out and h[0] < out[-1][1]:
            continue
        out.append(h)
    return out


_OCR_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1", "S": "5", "B": "8"})


def normalize_ocr(text):
    """숫자 위주 문자열이면 OCR 오인식(O→0, l→1 등)을 보정. 길이는 그대로 유지."""
    alnum = [c for c in text if c.isalnum()]
    if alnum and sum(c.isdigit() for c in alnum) / len(alnum) >= 0.6 and "@" not in text:
        return text.translate(_OCR_FIX)
    return text


def is_label(text):
    return bool(LABEL_RE.match(text))


def label_has_value(text):
    m = LABEL_RE.match(text)
    return bool(m) and len(text[m.end():].strip()) >= 2


def mask_text(s):
    """자막용 마스킹: 숫자/글자를 * 로."""
    return "".join("*" if (c.isalnum() or "가" <= c <= "힣") else c for c in s)
