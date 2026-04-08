import logging
from pathlib import Path

import gradio as gr

from core.pipeline import process_video, PipelineProgress, PipelineResult
from utils.storage import save_task_output
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

if config.COOKIES_FILE:
    logger.info("Cookies 文件已加载: %s", config.COOKIES_FILE)
elif config.COOKIES_FILE_CONFIGURED:
    logger.warning("COOKIES_FILE 指定的文件不存在，将不使用 cookies")

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

    # Save task output to persistent directory and use paths for download
    paths = save_task_output(result_obj)

    srt_file = str(paths.transcript_srt) if paths.transcript_srt else None
    txt_file = str(paths.transcript_txt) if paths.transcript_txt else None
    learning_file = str(paths.learning_md) if paths.learning_md else None
    summary_file = str(paths.summary_md) if paths.summary_md else None

    yield (
        f"处理完成! 视频: {result_obj.title} (任务 ID: {result_obj.task_id})",
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


def parse_cli_args():
    """Parse command line arguments. Returns (url, model, language, output_dir, api_key)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="视频转文字工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="视频链接 (抖音/B站/YouTube)，不提供则启动 Web 界面",
    )
    parser.add_argument(
        "--model",
        default=config.WHISPER_MODEL_SIZE,
        choices=MODEL_CHOICES,
        help=f"Whisper 模型大小 (默认: {config.WHISPER_MODEL_SIZE})",
    )
    parser.add_argument(
        "--language",
        default="auto",
        help="语言代码: auto, zh, en, ja, ko (默认: auto)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录 (默认: output/<task_id>/)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="覆盖 DASHSCOPE_API_KEY 环境变量",
    )
    return parser.parse_args()


def run_cli(url: str, model_size: str, language: str, output_dir: Path | None):
    """Run video processing in CLI mode."""
    for event in process_video(url, model_size, language):
        if isinstance(event, PipelineProgress):
            pct = int(event.percent * 100)
            print(f"[{pct:3d}%] {event.message}")
        elif isinstance(event, PipelineResult):
            print(f"\n处理完成: {event.title}")
            print(f"任务 ID: {event.task_id}")
            paths = save_task_output(event, output_dir=output_dir)
            print("\n输出文件:")
            for name, path in [
                ("  文字稿 (Markdown)", paths.transcript_md),
                ("  纯文字稿 (TXT)", paths.transcript_txt),
                ("  字幕文件 (SRT)", paths.transcript_srt),
                ("  语言学习稿", paths.learning_md),
                ("  内容总结", paths.summary_md),
            ]:
                if path:
                    print(f"    {name}: {path}")


if __name__ == "__main__":
    args = parse_cli_args()

    if args.url:
        # CLI mode
        import os

        if args.api_key:
            os.environ["DASHSCOPE_API_KEY"] = args.api_key

        run_cli(args.url, args.model, args.language, args.output_dir)
    else:
        # Web mode
        demo = build_ui()
        demo.queue()
        demo.launch(
            server_name="0.0.0.0",
            server_port=7860,
            theme=gr.themes.Soft(),
            css=CUSTOM_CSS,
        )
