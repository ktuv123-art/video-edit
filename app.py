"""웹 UI: 영상을 올리면 자동 편집된 결과를 돌려준다. (run_ui.bat 으로 실행)"""
import queue
import threading
import traceback

import gradio as gr

from vauto.config import Config
from vauto.pipeline import process


def run(video, model, max_pause, cut_silence, cut_fillers, aggressive, subs, burn, font_scale,
        mosaic, faces, beep, ocr_interval):
    if not video:
        yield None, None, "", "영상을 먼저 올려주세요."
        return
    cfg = Config(
        whisper_model=model, max_pause=max_pause, cut_silence=cut_silence, cut_fillers=cut_fillers,
        aggressive_fillers=aggressive, subtitles=subs, burn_subtitles=burn, font_scale=font_scale,
        mosaic_text_pii=mosaic, mosaic_faces=faces, beep_spoken_pii=beep, ocr_interval=ocr_interval,
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
            video = gr.Video(label="원본 영상 업로드", sources=["upload"])
            with gr.Accordion("컷 편집", open=True):
                cut_silence = gr.Checkbox(True, label="무음 구간 제거")
                cut_fillers = gr.Checkbox(True, label="필러워드 제거 (어, 음, 으음 …)")
                aggressive = gr.Checkbox(False, label="머뭇거리는 '그…', '저…', '아…' 도 제거")
                max_pause = gr.Slider(0.15, 1.0, 0.40, step=0.05, label="유지할 쉼 길이(초) — 클수록 덜 자름")
            with gr.Accordion("자막", open=True):
                subs = gr.Checkbox(True, label="자막 생성")
                burn = gr.Checkbox(True, label="영상에 자막 입히기 (끄면 SRT 파일만)")
                font_scale = gr.Slider(0.6, 1.6, 1.0, step=0.05, label="자막 크기")
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

    btn.click(run, [video, model, max_pause, cut_silence, cut_fillers, aggressive, subs, burn, font_scale,
                    mosaic, faces, beep, ocr_interval], [out_video, out_files, report, log])

if __name__ == "__main__":
    from vauto.pipeline import ROOT
    (ROOT / "output").mkdir(exist_ok=True)
    demo.queue().launch(inbrowser=True, server_name="127.0.0.1", allowed_paths=[str(ROOT / "output")])
