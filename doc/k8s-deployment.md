# Kubernetes 部署指南

本文档面向调度此 Docker 镜像的 Spring Boot / k8s 开发人员。

---

## 镜像构建

```bash
docker build -t video-to-text:latest \
  --build-arg WHISPER_MODEL=medium \
  --build-arg WHISPER_COMPUTE_TYPE=int8 \
  .
```

### Build Args

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `WHISPER_MODEL` | `medium` | Whisper 模型大小 (tiny/base/small/medium/large-v3) |
| `WHISPER_COMPUTE_TYPE` | `int8` | 量化类型，GPU 环境可用 `float16` |

---

## 基础运行

```bash
docker run -d \
  -p 7860:7860 \
  -e DASHSCOPE_API_KEY=your-api-key \
  video-to-text:latest
```

启动后 Web UI 可通过 `http://localhost:7860` 访问。

---

## CLI 模式（推荐用于 k8s 任务）

Web 模式需要长期运行的服务，而 CLI 模式更适合任务调度：

```bash
docker run --rm \
  -e DASHSCOPE_API_KEY=your-api-key \
  video-to-text:latest \
  python app.py "https://www.youtube.com/watch?v=xxx"
```

### CLI 参数

| 参数 | 说明 |
|------|------|
| `python app.py <url>` | 视频链接（必填） |
| `--model` | Whisper 模型 (tiny/base/small/medium/large-v3) |
| `--language` | 语言代码 (auto/zh/en/ja/ko) |
| `--output-dir` | 输出目录（默认写入容器内 `/app/output`） |
| `--job-id` | 自定义任务 ID，用于指定输出目录名称 |
| `--api-key` | 覆盖 DASHSCOPE_API_KEY |

### 示例

```bash
# 处理 B 站视频
docker run --rm \
  -e DASHSCOPE_API_KEY=sk-xxx \
  video-to-text:latest \
  python app.py "https://www.bilibili.com/video/BV1UaPmzrESw" \
    --model medium \
    --language auto

# 指定输出目录（需要挂载 volume）
docker run --rm \
  -e DASHSCOPE_API_KEY=sk-xxx \
  -v /host/output:/app/output \
  video-to-text:latest \
  python app.py "https://www.youtube.com/watch?v=xxx" \
    --job-id my-task-001 \
    --output-dir /app/output
```

### 与调用方集成

通过 `--job-id` 参数，调用方可以指定输出目录名称，便于获取任务结果：

```bash
docker run --rm \
  -e DASHSCOPE_API_KEY=sk-xxx \
  -v /host/output:/app/output \
  video-to-text:latest \
  python app.py "https://www.youtube.com/watch?v=xxx" \
    --job-id "spring-boot-job-123" \
    --output-dir /app/output
```

任务完成后，输出文件在：
```
/host/output/spring-boot-job-123/
├── <视频标题>.md
├── <视频标题>.txt
└── ...
```

---

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `DASHSCOPE_API_KEY` | 是 | - | 阿里百炼 API Key |
| `DASHSCOPE_BASE_URL` | 否 | `https://coding.dashscope.aliyuncs.com/v1` | API 地址 |
| `DASHSCOPE_MODEL` | 否 | `qwen3.5-plus` | LLM 模型 |
| `WHISPER_MODEL_SIZE` | 否 | `medium` | Whisper 模型大小 |
| `WHISPER_COMPUTE_TYPE` | 否 | `int8` | 量化类型 (int8/float16/float32) |
| `WHISPER_DEVICE` | 否 | `cpu` | 设备类型 (cpu/cuda)，GPU 节点设为 `cuda` |
| `MAX_VIDEO_DURATION` | 否 | `14400` | 最大视频时长（秒） |
| `OUTPUT_DIR` | 否 | `/app/output` | 输出根目录 |
| `COOKIES_FILE` | 否 | `/app/cookies.txt` | Netscape 格式 cookies 文件路径 |

---

## k8s Deployment 示例

### Job（CLI 任务模式）

推荐使用 **Job** 而非 Deployment 来执行一次性任务：

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: video-to-text-task
spec:
  template:
    spec:
      containers:
        - name: video-to-text
          image: video-to-text:latest
          command: ["python", "app.py"]
          args:
            - "https://www.youtube.com/watch?v=xxx"
            - "--model"
            - "medium"
            - "--job-id"
            - "spring-boot-job-123"
            - "--output-dir"
            - "/app/output"
          env:
            - name: DASHSCOPE_API_KEY
              valueFrom:
                secretKeyRef:
                  name: dashscope-secret
                  key: api-key
          volumeMounts:
            - name: output-volume
              mountPath: /app/output
      volumes:
        - name: output-volume
          persistentVolumeClaim:
            claimName: video-output-pvc
      restartPolicy: Never
  backoffLimit: 2
```

### Deployment（长期运行 Web 服务模式）

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: video-to-text-web
spec:
  replicas: 2
  selector:
    matchLabels:
      app: video-to-text
  template:
    metadata:
      labels:
        app: video-to-text
    spec:
      containers:
        - name: web
          image: video-to-text:latest
          ports:
            - containerPort: 7860
          env:
            - name: DASHSCOPE_API_KEY
              valueFrom:
                secretKeyRef:
                  name: dashscope-secret
                  key: api-key
          resources:
            requests:
              memory: "4Gi"
              cpu: "2"
            limits:
              memory: "8Gi"
              cpu: "4"
          livenessProbe:
            httpGet:
              path: /
              port: 7860
            initialDelaySeconds: 60
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /
              port: 7860
            initialDelaySeconds: 30
            periodSeconds: 10
```

### Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: video-to-text-web
spec:
  selector:
    app: video-to-text
  ports:
    - port: 80
      targetPort: 7860
  type: ClusterIP
```

---

## 输出文件

任务完成后，输出文件保存在 `--output-dir` 指定的目录（默认 `/app/output`）：

```
output/<task_id>/
├── <视频标题>.md          # 文字稿 (Markdown)
├── <视频标题>.txt         # 纯文字稿
├── <视频标题>.srt         # SRT 字幕
├── <视频标题>_学习稿.md   # 语言学习稿 (非中文视频)
└── <视频标题>_总结.md    # AI 总结
```

**注意**：k8s Job 执行完毕后容器会被删除，**必须**通过 Volume 挂载将输出文件持久化到宿主机或 NFS。

---

## GPU 支持

如需 GPU 加速：

1. **NVIDIA GPU**：
   - 使用 nvidia-docker 或 Container Device Interface (CDI)
   - 设置 `WHISPER_DEVICE=cuda` 和 `WHISPER_COMPUTE_TYPE=float16`

2. **k8s GPU 配置**：
   ```yaml
   containers:
     - name: video-to-text
       image: video-to-text:latest
       resources:
         limits:
           nvidia.com/gpu: 1
       env:
         - name: WHISPER_DEVICE
           value: cuda
         - name: WHISPER_COMPUTE_TYPE
           value: float16
   ```

---

## 资源需求参考

| Whisper 模型 | 内存需求 (CPU) | GPU 显存 |
|-------------|---------------|----------|
| tiny | ~1GB | ~1GB |
| base | ~1GB | ~1GB |
| small | ~2GB | ~2GB |
| medium | ~5GB | ~3GB |
| large-v3 | ~10GB | ~6GB |

建议：CPU 模式预留 8GB 内存，medium 模型转录 15 分钟视频约需 3-5 分钟。

---

## 健康检查

Dockerfile 内置了 Health Check：

```bash
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:7860/ || exit 1
```

仅适用于 Web 模式。CLI 模式 Job 无需健康检查。
