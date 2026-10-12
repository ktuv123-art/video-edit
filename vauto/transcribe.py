"""faster-whisper로 단어 단위 타임스탬프 대본 추출."""
import json
import os
from pathlib import Path


def _add_cuda_dlls():
    # torch(cu128)에 들어있는 cuDNN/cuBLAS DLL을 CTranslate2가 찾을 수 있게 한다
    try:
        import torch  # noqa: F401
        lib = Path(torch.__file__).parent / "lib"
        if lib.exists():
            os.add_dll_directory(str(lib))
            os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


# 필러를 받아적도록 유도하는 프롬프트 (Whisper는 기본적으로 "어/음"을 생략하는 경향이 있음)
FILLER_PROMPT = "음, 어, 그러니까 이제 어... 음... 저기 그, 네. 어 그래서요."


def transcribe(wav_path, cfg, log=print):
    _add_cuda_dlls()
    from faster_whisper import WhisperModel

    device = cfg.device
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"

    def load(dev):
        ctype = "float16" if dev == "cuda" else "int8"
        log(f"음성 인식 모델 로딩: {cfg.whisper_model} ({dev}, {ctype}) — 첫 실행은 모델 다운로드로 오래 걸립니다")
        return WhisperModel(cfg.whisper_model, device=dev, compute_type=ctype)

    from .media import load_wav
    audio = load_wav(wav_path)  # 파일 경로 대신 배열로 넘김 (PyAV 버전 호환 문제 회피)

    def run_model(model):
        segments, info = model.transcribe(
            audio,
            language=cfg.language,
            word_timestamps=True,
            initial_prompt=FILLER_PROMPT,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=1000, speech_pad_ms=400),
            hallucination_silence_threshold=2.0,
            beam_size=5,
        )
        words = []
        for si, seg in enumerate(segments):
            log(f"  [{seg.start:7.2f}s] {seg.text.strip()}")
            for w in seg.words or []:
                if not w.word.strip():
                    continue
                words.append({"text": w.word, "start": round(w.start, 3), "end": round(w.end, 3),
                              "prob": round(w.probability, 3), "seg": si})
        return words

    try:
        words = run_model(load(device))
    except Exception as e:
        if device != "cuda":
            raise
        log(f"GPU 음성 인식 실패({e.__class__.__name__}: {e}) → CPU로 다시 시도")
        words = run_model(load("cpu"))
    return words


def load_or_transcribe(wav_path, cache_path, cfg, log=print):
    cache_path = Path(cache_path)
    key = {"model": cfg.whisper_model, "language": cfg.language}
    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data.get("key") == key:
            log("저장된 대본 사용 (다시 인식하려면 work 폴더의 transcript.json 삭제)")
            return data["words"]
    words = transcribe(wav_path, cfg, log)
    cache_path.write_text(json.dumps({"key": key, "words": words}, ensure_ascii=False, indent=1), encoding="utf-8")
    return words
