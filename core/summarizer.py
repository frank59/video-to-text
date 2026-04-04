import logging
from typing import Generator

from openai import OpenAI

import config
from prompts.summarize import (
    SYSTEM_PROMPT,
    SUMMARIZE_TEMPLATE,
    CHUNK_SUMMARIZE_TEMPLATE,
    MERGE_SUMMARY_TEMPLATE,
)

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_CHARS = 100_000
CHUNK_SIZE = 80_000
CHUNK_OVERLAP = 2_000


class SummarizeError(Exception):
    pass


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Get or create the OpenAI-compatible client for DashScope."""
    global _client
    if _client is None:
        if not config.DASHSCOPE_API_KEY:
            raise SummarizeError("请配置 DASHSCOPE_API_KEY 环境变量（在 .env 文件中设置）")
        _client = OpenAI(
            api_key=config.DASHSCOPE_API_KEY,
            base_url=config.DASHSCOPE_BASE_URL,
        )
    return _client


def _call_stream(system: str, user: str) -> Generator[str, None, None]:
    """Call LLM API with streaming and yield text chunks."""
    client = _get_client()
    try:
        stream = client.chat.completions.create(
            model=config.DASHSCOPE_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        raise SummarizeError(f"LLM API 调用失败: {e}") from e


def _call_full(system: str, user: str) -> str:
    """Call LLM API and return full response text."""
    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=config.DASHSCOPE_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        raise SummarizeError(f"LLM API 调用失败: {e}") from e


def _split_transcript(transcript: str) -> list[str]:
    """Split a long transcript into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(transcript):
        end = start + CHUNK_SIZE
        chunks.append(transcript[start:end])
        start = end - CHUNK_OVERLAP
    return chunks


def summarize_stream(transcript: str) -> Generator[str, None, None]:
    """Summarize transcript with streaming output.

    Yields partial text as it arrives from the LLM.
    For very long transcripts, does chunked summarization.
    """
    if len(transcript) <= MAX_TRANSCRIPT_CHARS:
        user_prompt = SUMMARIZE_TEMPLATE.format(transcript=transcript)
        yield from _call_stream(SYSTEM_PROMPT, user_prompt)
    else:
        logger.info("文稿过长 (%d 字)，使用分块总结", len(transcript))
        chunks = _split_transcript(transcript)

        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            yield f"\n\n> 正在分析第 {i + 1}/{len(chunks)} 部分...\n\n"
            user_prompt = CHUNK_SUMMARIZE_TEMPLATE.format(
                chunk_index=i + 1,
                total_chunks=len(chunks),
                transcript=chunk,
            )
            summary = _call_full(SYSTEM_PROMPT, user_prompt)
            chunk_summaries.append(f"### 第 {i + 1} 部分\n{summary}")

        yield "\n\n> 正在整合总结...\n\n"
        combined = "\n\n".join(chunk_summaries)
        user_prompt = MERGE_SUMMARY_TEMPLATE.format(chunk_summaries=combined)
        yield from _call_stream(SYSTEM_PROMPT, user_prompt)
