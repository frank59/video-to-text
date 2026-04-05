import logging
import re
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


def _safe_filename(title: str) -> str:
    """Sanitize video title for use as filename, replacing special characters with '_'."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', title)
    name = name.strip('. ')
    return name or "video"


def run_pipeline(url: str, model_size: str, language: str, progress=gr.Progress()):
    """Main processing function wired to the Gradio UI.

    This is a generator that yields updates for each output component:
    (status, transcript_md, pure_text, learning_md, summary_md, srt_file, txt_file, result_state)
    """
    empty = ("请输入视频链接", "", "", "", "", None, None, None, None, None)
    if not url.strip():
        yield empty
        return

    transcript_md = ""
    pure_text = ""
    learning_md = ""
    summary_md = ""
    result_obj = None

    def _make_output(status):
        return (
            status,
            transcript_md,
            pure_text,
            learning_md,
            summary_md,
            None,
            None,
            None,
            None,
            result_obj,
        )

    for event in process_video(url, model_size, language):
        if isinstance(event, PipelineProgress):
            progress(event.percent, desc=event.message)

            if event.transcript_md:
                transcript_md = event.transcript_md
            if event.pure_text:
                pure_text = event.pure_text
            if event.partial_learning:
                learning_md = event.partial_learning
            if event.partial_summary:
                summary_md = event.partial_summary

            if "错误" in event.message or "失败" in event.message:
                yield _make_output(f"**{event.message}**")
                return

            yield _make_output(event.message)

        elif isinstance(event, PipelineResult):
            result_obj = event
            transcript_md = event.transcript_markdown
            pure_text = event.transcript_pure
            learning_md = event.learning_transcript
            summary_md = event.summary

    if result_obj is None:
        yield _make_output("处理未完成")
        return

    # Generate export files with video title as filename
    srt_file = None
    txt_file = None
    learning_file = None
    summary_file = None

    safe_name = _safe_filename(result_obj.title)
    export_dir = Path(tempfile.mkdtemp())

    if result_obj.transcript_srt:
        srt_path = export_dir / f"{safe_name}.srt"
        srt_path.write_text(result_obj.transcript_srt, encoding="utf-8")
        srt_file = str(srt_path)

    if result_obj.transcript_pure:
        txt_path = export_dir / f"{safe_name}.txt"
        txt_path.write_text(result_obj.transcript_pure, encoding="utf-8")
        txt_file = str(txt_path)

    if result_obj.learning_transcript:
        learning_path = export_dir / f"{safe_name}_学习稿.md"
        learning_path.write_text(result_obj.learning_transcript, encoding="utf-8")
        learning_file = str(learning_path)

    if result_obj.summary:
        summary_path = export_dir / f"{safe_name}_总结.md"
        summary_path.write_text(result_obj.summary, encoding="utf-8")
        summary_file = str(summary_path)

    yield (
        f"处理完成! 视频: {result_obj.title}",
        transcript_md,
        pure_text,
        learning_md,
        summary_md,
        srt_file,
        txt_file,
        learning_file,
        summary_file,
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
            with gr.Tab("纯文字稿"):
                pure_text_output = gr.Markdown(
                    value="",
                    elem_classes=["transcript-box"],
                )
            with gr.Tab("语言学习稿"):
                learning_output = gr.Markdown(
                    value="*非中文视频自动生成逐句翻译和核心词汇表*",
                    elem_classes=["summary-box"],
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
                    txt_download = gr.File(label="TXT 纯文字稿")
                with gr.Row():
                    learning_download = gr.File(label="语言学习稿 (Markdown)")
                    summary_download = gr.File(label="内容总结 (Markdown)")

        # Hidden state to store full result
        result_state = gr.State(None)

        outputs = [
            status_text,
            transcript_output,
            pure_text_output,
            learning_output,
            summary_output,
            srt_download,
            txt_download,
            learning_download,
            summary_download,
            result_state,
        ]

        # --- Event Wiring ---
        submit_btn.click(
            fn=run_pipeline,
            inputs=[url_input, model_dropdown, lang_dropdown],
            outputs=outputs,
        )

        url_input.submit(
            fn=run_pipeline,
            inputs=[url_input, model_dropdown, lang_dropdown],
            outputs=outputs,
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
