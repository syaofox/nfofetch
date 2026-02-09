##########
# 构建阶段：只用于安装依赖
##########
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 只复制依赖声明，最大化缓存利用率
COPY pyproject.toml .

# 安装运行时依赖到单独前缀目录，后面拷贝进最终镜像
RUN pip install --upgrade pip && \
    pip install \
      "fastapi>=0.115.0" \
      "uvicorn[standard]>=0.30.0" \
      "jinja2>=3.1.0" \
      "httpx>=0.27.0" \
      "selectolax>=0.3.0" \
      "pydantic>=2.0.0" \
      "python-multipart>=0.0.9" \
      "curl-cffi>=0.14.0" \
      --prefix=/install


##########
# 运行阶段：尽量精简，只包含 Python + 依赖 + 应用代码
##########
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 拷贝构建阶段安装好的依赖
COPY --from=builder /install /usr/local

# 拷贝应用代码
COPY app app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

