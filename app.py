"""웹 UI: 영상을 올리면 자동 편집된 결과를 돌려준다. (run_ui.bat 으로 실행)"""
import queue
import threading
import traceback

import gradio as gr

from vauto.config import Config
from vauto.pipeline import process
from vauto.preview import extract_frame, image_size, render_preview


def _pos_label(pos):
    if not pos:
        return "자막 위치: **아래 가운데 (기본)**"
    return f"자막 위치: 가로 **{pos[0] * 100:.0f}%**, 세로 **{pos[1] * 100:.0f}%** (화면 왼쪽 위 기준)"


def on_video(video, font_scale):
    """영상을 올리면 대표 장면을 뽑아 미리보기를 보여주고 위치는 기본값으로 초기화."""
    if not video:
        return None, None, None, _pos_label(None)
    try:
        frame = extract_frame(video)
    except Exception as e:
        return None, None, None, f"미리보기를 만들지 못했습니다: {e}"
    return frame, render_preview(frame, None, font_scale), None, _pos_label(None)


def on_pick(frame, pos, font_scale, evt: gr.SelectData):
    """미리보기 화면을 클릭하면 그 지점이 자막 중심이 된다."""
    if not frame:
        return gr.update(), pos, gr.update()
    w, h = image_size(frame)
    x, y = evt.index
    pos = (min(max(x / w, 0.0), 1.0), min(max(y / h, 0.0), 1.0))
    return render_preview(frame, pos, font_scale), pos, _pos_label(pos)


def on_preset(frame, font_scale, where):
    if not frame:
        return gr.update(), None, gr.update()
    pos = {"top": (0.5, 0.10), "middle": (0.5, 0.50), "bottom": None}[where]
    return render_preview(frame, pos, font_scale), pos, _pos_label(pos)


def on_scale(frame, pos, font_scale):
    if not frame:
        return gr.update()
    return render_preview(frame, pos, font_scale)


def run(video, model, max_pause, cut_silence, cut_fillers, aggressive, subs, burn, font_scale,
        mosaic, faces, beep, ocr_interval, sub_pos):
    if not video:
        yield None, None, "", "영상을 먼저 올려주세요."
        return
    cfg = Config(
        whisper_model=model, max_pause=max_pause, cut_silence=cut_silence, cut_fillers=cut_fillers,
        aggressive_fillers=aggressive, subtitles=subs, burn_subtitles=burn, font_scale=font_scale,
        mosaic_text_pii=mosaic, mosaic_faces=faces, beep_spoken_pii=beep, ocr_interval=ocr_interval,
        sub_pos=tuple(sub_pos) if sub_pos else None,
    )
    q, logs, box = queue.Queue(), [], {}

    def work():
        try:
            box["result"] = process(video, cfg, log=q.put)
        except Exception as e:
            q.put(f"✖ 오류: {e}")
            q.put(traceback.format_exc())
        q.put(None)

    threading.Thread(target=work, daemon=True).start()
    while True:
        msg = q.get()
        if msg is None:
            break
        logs.append(str(msg))
        yield None, None, "", "\n".join(logs[-400:])
    r = box.get("result")
    if r:
        files = [str(r["video"]), str(r["report"])] + ([str(r["srt"])] if r["srt"] else [])
        yield str(r["video"]), files, r["report_text"], "\n".join(logs[-400:])


with gr.Blocks(title="영상 자동 편집") as demo:
    gr.Markdown("## 🎬 영상 자동 편집\n무음·필러(어, 음) 컷 → 컷마다 싱크 맞춘 자막 → 화면/음성 속 개인정보 모자이크·삐 처리")
    with gr.Row():
        with gr.Column(scale=1):
            video = gr.File(label="원본 영상 업로드", file_types=["video"], file_count="single", type="filepath")
            with gr.Accordion("컷 편집", open=True):
                cut_silence = gr.Checkbox(True, label="무음 구간 제거")
                cut_fillers = gr.Checkbox(True, label="필러워드 제거 (어, 음, 으음 …)")
                aggressive = gr.Checkbox(False, label="머뭇거리는 '그…', '저…', '아…' 도 제거")
                max_pause = gr.Slider(0.15, 1.0, 0.40, step=0.05, label="유지할 쉼 길이(초) — 클수록 덜 자름")
            with gr.Accordion("자막", open=True):
                subs = gr.Checkbox(True, label="자막 생성")
                burn = gr.Checkbox(True, label="영상에 자막 입히기 (끄면 SRT 파일만)")
                font_scale = gr.Slider(0.6, 1.6, 1.0, step=0.05, label="자막 크기")
                gr.Markdown("**자막 위치** — 아래 화면에서 자막을 놓고 싶은 곳을 **마우스로 클릭**하세요. 클릭한 점이 자막의 가운데가 됩니다.")
                preview = gr.Image(label="클릭해서 자막 위치 지정", interactive=False, type="pil")
                pos_label = gr.Markdown(_pos_label(None))
                with gr.Row():
                    p_top = gr.Button("위쪽", size="sm")
                    p_mid = gr.Button("가운데", size="sm")
                    p_bot = gr.Button("아래(기본)", size="sm")
            with gr.Accordion("개인정보", open=True):
                mosaic = gr.Checkbox(True, label="화면 속 전화번호·주소·이메일·주민번호·차량번호 등 모자이크")
                beep = gr.Checkbox(True, label="말로 나온 전화번호 등 삐 처리 + 자막 가림")
                faces = gr.Checkbox(False, label="모든 얼굴 모자이크 (실험적)")
                ocr_interval = gr.Slider(0.2, 2.0, 0.5, step=0.1, label="화면 검사 간격(초) — 화면이 많이 움직이면 작게")
            with gr.Accordion("고급", open=False):
                model = gr.Dropdown(["large-v3", "large-v3-turbo", "medium", "small"], value="large-v3",
                                    label="음성 인식 모델 (large-v3 = 가장 정확)")
            btn = gr.Button("편집 시작", variant="primary")
        with gr.Column(scale=1):
            out_video = gr.Video(label="편집 결과")
            out_files = gr.File(label="결과 파일 (영상 · 자막 SRT · 리포트)", file_count="multiple")
            report = gr.Textbox(label="리포트", lines=8)
            log = gr.Textbox(label="진행 로그", lines=14, max_lines=14, autoscroll=True)

    frame_state = gr.State(None)   # 미리보기용 원본 장면 경로
    pos_state = gr.State(None)     # 선택한 자막 위치 (x, y) 비율. None = 기본

    video.change(on_video, [video, font_scale], [frame_state, preview, pos_state, pos_label])
    preview.select(on_pick, [frame_state, pos_state, font_scale], [preview, pos_state, pos_label])
    font_scale.change(on_scale, [frame_state, pos_state, font_scale], [preview])
    p_top.click(lambda f, s: on_preset(f, s, "top"), [frame_state, font_scale], [preview, pos_state, pos_label])
    p_mid.click(lambda f, s: on_preset(f, s, "middle"), [frame_state, font_scale], [preview, pos_state, pos_label])
    p_bot.click(lambda f, s: on_preset(f, s, "bottom"), [frame_state, font_scale], [preview, pos_state, pos_label])

    btn.click(run, [video, model, max_pause, cut_silence, cut_fillers, aggressive, subs, burn, font_scale,
                    mosaic, faces, beep, ocr_interval, pos_state], [out_video, out_files, report, log])

if __name__ == "__main__":
    from vauto.pipeline import ROOT
    (ROOT / "output").mkdir(exist_ok=True)
    demo.queue().launch(inbrowser=True, server_name="127.0.0.1", allowed_paths=[str(ROOT / "output")])
