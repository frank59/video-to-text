# Web API 接口文档

> 适用于 Gradio Web 界面模式

## 基础信息

| 项目 | 值 |
|------|-----|
| 服务地址 | `http://localhost:7860` (本地) |
| API 端点 | `/api/predict` |
| API 文档 | `/docs` |
| 请求方法 | POST |
| 认证 | 无 |

## 接口详情

### POST /api/predict

视频转文字处理接口

**请求体 (JSON)：**

```json
{
  "data": [
    "https://www.youtube.com/watch?v=xxx",   // url: 视频链接
    "medium",                                // model_size: Whisper 模型
    "auto"                                   // language: 语言 (auto/zh/en/ja/ko)
  ]
}
```

**响应体 (JSON)：**

```json
{
  "data": [
    "处理完成! 视频: xxx (任务 ID: xxx)",    // status_text
    "**[00:00]** 文字稿内容...",            // transcript_output (Markdown)
    "纯文字稿内容...",                        // pure_text_output
    "",                                      // learning_output (非中文视频才有内容)
    "## 一句话概述\n...",                     // summary_output
    null,                                    // srt_download (文件路径)
    null,                                    // txt_download (文件路径)
    null,                                    // learning_download (文件路径)
    null,                                    // summary_download (文件路径)
    null                                     // result_state
  ]
}
```

**响应字段说明：**

| 索引 | 字段名 | 类型 | 说明 |
|------|--------|------|------|
| 0 | status_text | string | 处理状态消息 |
| 1 | transcript_output | string | 带时间戳的文字稿 (Markdown) |
| 2 | pure_text_output | string | 纯文字稿 (无时间戳) |
| 3 | learning_output | string | 语言学习稿 (非中文视频) |
| 4 | summary_output | string | AI 内容总结 (Markdown) |
| 5 | srt_download | string\|null | SRT 字幕文件路径 |
| 6 | txt_download | string\|null | TXT 纯文字稿文件路径 |
| 7 | learning_download | string\|null | 语言学习稿 Markdown 文件路径 |
| 8 | summary_download | string\|null | 内容总结 Markdown 文件路径 |
| 9 | result_state | null | 保留字段 |

## 调用示例

### cURL

```bash
curl -X POST http://localhost:7860/api/predict \
  -H "Content-Type: application/json" \
  -d '{"data": ["https://www.bilibili.com/video/BV1UaPmzrESw", "medium", "auto"]}'
```

### Python

```python
import requests

response = requests.post(
    "http://localhost:7860/api/predict",
    json={
        "data": [
            "https://www.bilibili.com/video/BV1UaPmzrESw",
            "medium",
            "auto"
        ]
    }
)
result = response.json()
print(result["data"][0])  # 状态消息
print(result["data"][1])  # 文字稿
```

### Java

```java
HttpClient client = HttpClient.newHttpClient();
String requestBody = """
    {"data": ["https://www.bilibili.com/video/BV1UaPmzrESw", "medium", "auto"]}
    """;

HttpRequest request = HttpRequest.newBuilder()
    .uri(URI.create("http://localhost:7860/api/predict"))
    .header("Content-Type", "application/json")
    .POST(HttpRequest.BodyPublishers.ofString(requestBody))
    .build();

HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
System.out.println(response.body());
```

## API 文档页面

启动服务后，可通过浏览器访问：

- Swagger UI: `http://localhost:7860/docs`
- Redoc: `http://localhost:7860/redoc`

## 注意事项

1. **处理时间长**：视频转录需要数分钟，建议：
   - 使用异步调用
   - 通过轮询或 WebSocket 等待结果
   - 或使用 CLI 模式获取进度

2. **文件下载**：返回的文件路径是服务器本地路径，外部调用时需要通过 `/file` 端点访问

3. **流式响应**：`run_pipeline` 是生成器函数，Gradio 会等待完成后返回最终结果

4. **推荐方式**：对于程序化调用，**推荐使用 CLI 模式** + `progress.json` 追踪，可靠性更高

## 与 CLI 模式对比

| 特性 | Web API | CLI + progress.json |
|------|---------|---------------------|
| 调用方式 | HTTP 请求 | 进程执行 |
| 进度追踪 | 需要轮询 | 通过 progress.json |
| 任务状态 | 仅最终结果 | 完整状态快照 |
| k8s 集成 | 需网络暴露 | Job 模式更合适 |
| 可靠性 | 受网络影响 | 独立进程，更稳定 |

## 健康检查

```bash
curl http://localhost:7860/
```

返回 HTML 页面表示服务正常运行。
