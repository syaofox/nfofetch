##########
# 构建阶段：使用 uv 安装依赖（基于 uv.lock 锁定版本）
##########
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 安装 uv
RUN pip install --no-cache-dir uv

# 先只复制依赖声明，最大化缓存利用率
COPY pyproject.toml uv.lock ./

# 仅安装依赖（不安装项目本身），后续 app/ 变更时跳过这层缓存
RUN uv sync --frozen --no-dev --no-install-project

# 拷贝应用代码后再安装项目自身
COPY app app
RUN uv sync --frozen --no-dev


##########
# 运行阶段：只包含 Python + 依赖 + 应用代码
##########
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装 ffprobe（视频分辨率）和 Chromium 系统依赖（Playwright 浏览器）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        fonts-freefont-ttf \
        libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
        libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 \
        libpango-1.0-0 libcairo2 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 拷贝构建阶段的虚拟环境（与 runtime 同一 Python 版本，路径兼容）
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/app/.playwright-browsers

# 安装 Playwright Chromium 浏览器（用于 DMM 站点 JS 渲染）
RUN playwright install chromium && \
    chmod -R o+rX /app/.playwright-browsers

# 拷贝应用代码 + 版本信息
COPY pyproject.toml .
COPY app app

# 入口脚本：启动时自动创建 /config、检查权限、设置 HOME
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
