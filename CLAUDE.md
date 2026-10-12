# CLAUDE.md

영상을 올리면 ① 무음·필러워드 컷 → ② 컷에 맞춘 싱크 자막 → ③ 개인정보 모자이크/삐 처리를 하는 자동 편집 프로그램.
사용자는 한국어를 쓴다. 답변·주석·UI 문구는 한국어로 작성한다.

## 실행

```bash
# 환경 설치 (torch CUDA 12.8 포함)
install.bat

# 웹 UI
run_ui.bat                      # = .venv\Scripts\python.exe app.py

# 명령줄
.venv\Scripts\python.exe main.py 영상.mp4 [--aggressive] [--max-pause 0.4] [--srt-only]
```

- Windows 11 + PowerShell 환경, GPU는 RTX 5070(CUDA). `ffmpeg`/`ffprobe`는 PATH에 있어야 한다(NVENC 사용 가능하면 GPU 인코딩).
- 한글 경로/출력 때문에 실행 시 `PYTHONUTF8=1`을 설정한다(.bat 파일에 이미 포함).
- 테스트 프레임워크는 없다. 변경 후에는 짧은 샘플 영상을 `main.py`로 돌려 `output/`의 영상·SRT·리포트를 직접 확인한다.

## 구조 (`vauto/`)

| 파일 | 역할 |
|---|---|
| `config.py` | `Config` 데이터클래스(모든 옵션), 필러워드 목록 |
| `media.py` | ffprobe/ffmpeg 래퍼, 오디오 에너지(dB) 분석, 적응형 무음 탐지, 인코더 선택 |
| `transcribe.py` | faster-whisper 단어 단위 타임스탬프 대본 (결과는 `work/<영상>/transcript.json`에 캐시) |
| `cutter.py` | 필러 표시 → 남길 구간 계산 → `TimeMap`(원본 시간↔편집본 시간) |
| `subtitles.py` | 편집본 타임라인 기준 자막(SRT + 화면용 ASS), 음성 개인정보 `*` 마스킹 |
| `pii.py` | 개인정보 정규식(전화·주민·카드·계좌·이메일·차량·주소·라벨값) |
| `mosaic.py` | EasyOCR로 화면 개인정보 탐지, 프레임별 모자이크 렌더 |
| `preview.py` | 웹 UI용 자막 위치 미리보기(대표 장면 추출 + 샘플 자막 그리기) |
| `render.py` | 컷 + 자막 burn-in + 삐 처리를 ffmpeg filter_complex 한 번으로 렌더 |
| `pipeline.py` | 전체 흐름 오케스트레이션과 리포트 작성 |

진입점: `main.py`(CLI), `app.py`(Gradio 웹 UI). 둘 다 `pipeline.process()`를 호출한다.

## 규칙

- **이해를 해치지 않는 편집이 최우선**: 쉼을 전부 없애지 말고 `max_pause`(기본 0.4초) 이하는 호흡으로 남긴다. 컷 위치는 가장 조용한 지점에 맞춘다.
- 자막 시간은 반드시 `TimeMap`으로 변환한 **편집본** 기준 시간을 쓴다. 원본 시간을 그대로 쓰지 않는다.
- 자막 위치는 `Config.sub_pos`(화면 비율 x,y, 중심 기준)이고 `None`이면 아래 가운데. 지정되면 ASS에 `{\an5\pos(x,y)}`를 쓰고 `subtitles.clamp_center`로 화면 밖 잘림을 막는다. 미리보기(`preview.py`)도 같은 함수를 써서 결과와 일치시킨다.
- Gradio UI 테스트 시 스크린샷이 어긋나 보일 수 있으니, 클릭 좌표는 JS로 요소의 실제 위치를 확인하고 정한다.
- 개인정보는 **놓치는 쪽이 더 위험**하다. 모자이크는 의심되면 가리는 쪽으로 기울이고, 두 OCR 샘플 사이 프레임은 양쪽 박스를 모두 가린다.
- 새 개인정보 패턴을 추가할 때는 `pii.find_pii`로 오탐 케이스(날짜, 가격, 버전 번호, 1588-xxxx 등)를 함께 확인한다.
- ffmpeg 필터 그래프는 `filter.txt`로 넘기고 `cwd=workdir`에서 실행한다(경로 이스케이프 문제 회피). 자막 폰트는 `work/.../fonts`에 복사해서 쓴다.
- Whisper는 PyAV 호환 문제 때문에 파일 경로 대신 numpy 배열(`load_wav`)로 넘긴다. 바꾸지 말 것.

## 커밋하지 않는 것

`.venv/`, `work/`, `output/`, 영상·오디오 파일, `.env`는 `.gitignore`로 제외되어 있다. 영상과 결과물에는 개인정보가 들어 있을 수 있으니 저장소에 올리지 않는다.
