"""명령줄 실행: python main.py 영상.mp4 [옵션]"""
import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

from vauto.config import Config
from vauto.pipeline import process


def main():
    ap = argparse.ArgumentParser(description="무음/필러 컷 → 싱크 자막 → 개인정보 모자이크 자동 편집")
    ap.add_argument("videos", nargs="+", help="편집할 영상 파일(여러 개 가능)")
    ap.add_argument("-o", "--out", help="출력 폴더 (기본: output)")
    ap.add_argument("--model", default="large-v3", help="Whisper 모델 (large-v3, large-v3-turbo, medium ...)")
    ap.add_argument("--cpu", action="store_true", help="GPU 대신 CPU 사용")
    ap.add_argument("--max-pause", type=float, default=0.40, help="유지할 최대 쉼 길이(초)")
    ap.add_argument("--no-silence-cut", action="store_true")
    ap.add_argument("--no-filler-cut", action="store_true")
    ap.add_argument("--aggressive", action="store_true", help="'그', '저', '아' 같은 머뭇거림도 제거")
    ap.add_argument("--no-subs", action="store_true")
    ap.add_argument("--srt-only", action="store_true", help="자막을 영상에 입히지 않고 SRT만 출력")
    ap.add_argument("--font-file", default="", help="자막 폰트 파일(.ttf/.otf)")
    ap.add_argument("--font-scale", type=float, default=1.0)
    ap.add_argument("--no-mosaic", action="store_true", help="화면 개인정보 모자이크 끄기")
    ap.add_argument("--faces", action="store_true", help="모든 얼굴 모자이크(실험적)")
    ap.add_argument("--no-beep", action="store_true", help="말로 나온 개인정보 삐 처리 끄기")
    ap.add_argument("--ocr-interval", type=float, default=0.5)
    a = ap.parse_args()

    cfg = Config(
        whisper_model=a.model, device="cpu" if a.cpu else "auto", max_pause=a.max_pause,
        cut_silence=not a.no_silence_cut, cut_fillers=not a.no_filler_cut, aggressive_fillers=a.aggressive,
        subtitles=not a.no_subs, burn_subtitles=not a.srt_only, font_file=a.font_file, font_scale=a.font_scale,
        mosaic_text_pii=not a.no_mosaic, mosaic_faces=a.faces, beep_spoken_pii=not a.no_beep,
        ocr_interval=a.ocr_interval,
    )
    failed = 0
    for v in a.videos:
        try:
            r = process(v, cfg, a.out)
            print("\n" + r["report_text"] + "\n")
        except Exception as e:
            failed += 1
            tb = traceback.format_exc()
            print(f"✖ {v}: {e}\n{tb}", file=sys.stderr)
            log = Path(__file__).parent / "output" / "error_log.txt"
            log.parent.mkdir(exist_ok=True)
            with log.open("a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {v}\n{tb}\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
