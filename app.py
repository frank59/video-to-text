import logging
import tempfile
from pathlib import Path

import gradio as gr

from core.pipeline import process_video, PipelineProgress, PipelineResult
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_CHOICES = ["tiny", "base", "small", "medium", "large-v3"]
LANGUAGE_CHOICES = [
    ("自动检测", "auto"),
    ("中文", "zh"),
    ("英文", "en"),
    ("日文", "ja"),
    ("韩文", "ko"),
]


def run_pipeline(url: str, model_size: str, language: str, progress=gr.Progress()):
    """Main processing function wired to the Gradio UI.

    This is a generator that yields updates for each output component:
    (status_text, transcript_md, summary_md, srt_file, txt_file, result_state)
    """
    if not url.strip():
        yield ("请输入视频链接", "", "", None, None, None)
        return

    transcript_md = ""
    summary_md = ""
    result_obj = None

    for event in process_video(url, model_size, language):
        if isinstance(event, PipelineProgress):
            progress(event.percent, desc=event.message)

            # Update transcript and summary from progress events
            if event.transcript_md:
                transcript_md = event.transcript_md
            if event.partial_summary:
                summary_md = event.partial_summary

            # Check if this is an error
            if "错误" in event.message or "失败" in event.message:
                yield (
                    f"**{event.message}**",
                    transcript_md,
                    summary_md,
                    None,
                    None,
                    result_obj,
                )
                return

            yield (
                event.message,
                transcript_md,
                summary_md,
                None,
                None,
                result_obj,
            )

        elif isinstance(event, PipelineResult):
            result_obj = event
            transcript_md = event.transcript_markdown
            summary_md = event.summary

    if result_obj is None:
        yield ("处理未完成", transcript_md, summary_md, None, None, None)
        return

    # Generate export files
    srt_file = None
    txt_file = None

    if result_obj.transcript_srt:
        srt_path = Path(tempfile.mktemp(suffix=".srt"))
        srt_path.write_text(result_obj.transcript_srt, encoding="utf-8")
        srt_file = str(srt_path)

    if result_obj.transcript_plain:
        txt_path = Path(tempfile.mktemp(suffix=".txt"))
        txt_path.write_text(result_obj.transcript_plain, encoding="utf-8")
        txt_file = str(txt_path)

    yield (
        f"处理完成! 视频: {result_obj.title}",
        transcript_md,
        summary_md,
        srt_file,
        txt_file,
        result_obj,
    )


CUSTOM_CSS = """
.status-text { font-size: 14px; min-height: 40px; }
.transcript-box { min-height: 300px; }
.summary-box { min-height: 300px; }
"""


def build_ui() -> gr.Blocks:
    """Build the Gradio Blocks interface."""
    with gr.Blocks(title="视频转文字工具") as demo:
        gr.Markdown("# 视频转文字工具\n支持抖音、B站、YouTube 视频链接，自动生成文字稿并总结内容")

        # --- Input Section ---
        with gr.Row():
            url_input = gr.Textbox(
                label="视频链接",
                placeholder="粘贴抖音、B站或YouTube视频链接...",
                scale=4,
            )
            submit_btn = gr.Button("开始处理", variant="primary", scale=1)

        with gr.Row():
            model_dropdown = gr.Dropdown(
                choices=MODEL_CHOICES,
                value=config.WHISPER_MODEL_SIZE,
                label="Whisper 模型",
                info="模型越大越准确，但速度越慢",
            )
            lang_dropdown = gr.Dropdown(
                choices=LANGUAGE_CHOICES,
                value="auto",
                label="语言",
                info="留空自动检测",
            )

        # --- Status ---
        status_text = gr.Markdown(
            value="等待输入...",
            elem_classes=["status-text"],
        )

        # --- Results Tabs ---
        with gr.Tabs():
            with gr.Tab("文字稿"):
                transcript_output = gr.Markdown(
                    value="",
                    elem_classes=["transcript-box"],
                )
            with gr.Tab("内容总结"):
                summary_output = gr.Markdown(
                    value="",
                    elem_classes=["summary-box"],
                )
            with gr.Tab("导出"):
                gr.Markdown("处理完成后可下载文件:")
                with gr.Row():
                    srt_download = gr.File(label="SRT 字幕文件")
                    txt_download = gr.File(label="TXT 文本文件")

        # Hidden state to store full result
        result_state = gr.State(None)

        # --- Event Wiring ---
        submit_btn.click(
            fn=run_pipeline,
            inputs=[url_input, model_dropdown, lang_dropdown],
            outputs=[
                status_text,
                transcript_output,
                summary_output,
                srt_download,
                txt_download,
                result_state,
            ],
        )

        # Also trigger on Enter key
        url_input.submit(
            fn=run_pipeline,
            inputs=[url_input, model_dropdown, lang_dropdown],
            outputs=[
                status_text,
                transcript_output,
                summary_output,
                srt_download,
                txt_download,
                result_state,
            ],
        )

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.queue()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        theme=gr.themes.Soft(),
        css=CUSTOM_CSS,
    )
