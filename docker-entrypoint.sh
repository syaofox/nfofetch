#!/bin/sh
set -e

# ============================================================
# nfofetch Docker 入口脚本
# 处理容器启动时的初始化工作，确保文件写入不会因权限问题失败
# ============================================================

# 1. 确保 /config 目录存在（解决 Issue 1：docker-compose 自动创建时 root 所有）
if [ ! -d "/config" ]; then
    mkdir -p /config
fi

# 2. 设置 HOME 环境变量，确保 Python Path.home() 返回有效路径
#    （解决 Issue 3：容器内 UID 可能不在 /etc/passwd 中）
#    Docker 对未知 UID 会设置 HOME=/，这里强制纠正到 /config
if [ "$HOME" = "/" ] || [ -z "$HOME" ]; then
    export HOME="/config"
fi

# 3. 验证关键目录的可写性（解决 Issue 2 + Issue 9）
_user_id=$(id -u)

if [ ! -w "/config" ]; then
    echo "WARNING: /config 不可写（UID $_user_id）。请检查卷挂载权限。" >&2
fi

if [ -n "$NFOFETCH_BROWSE_ROOT" ] && [ ! -d "$NFOFETCH_BROWSE_ROOT" ]; then
    echo "WARNING: NFOFETCH_BROWSE_ROOT（$NFOFETCH_BROWSE_ROOT）不存在。请检查卷挂载。" >&2
elif [ -n "$NFOFETCH_BROWSE_ROOT" ] && [ ! -w "$NFOFETCH_BROWSE_ROOT" ]; then
    echo "WARNING: NFOFETCH_BROWSE_ROOT（$NFOFETCH_BROWSE_ROOT）不可写。NFO/图片写入可能失败。" >&2
fi

# 验证 ffprobe 可用（解决 Issue 9）
if ! command -v ffprobe >/dev/null 2>&1; then
    echo "WARNING: ffprobe 未安装，视频分辨率提取将不可用。" >&2
fi

# 4. 执行主命令
exec "$@"
