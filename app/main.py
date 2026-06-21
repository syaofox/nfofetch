from __future__ import annotations

import asyncio
import base64
import functools
import logging
import os
import shutil
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.middleware import create_rate_limit_middleware
from app.schemas import MovieMetadata, Preset, ScrapeResult, UserSettings
from app.services.file_service import save_assets_for_existing_video
from app.services.file_utils import VIDEO_EXTENSIONS
from app.services.nfo_service import build_movie_nfo
from app.services.scrape_service import is_url, scrape_movie, search_movie
from app.services.settings_service import load_user_settings, save_user_settings

_log_level = os.getenv("NFOFETCH_LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.WARNING),
    format="%(levelname)s: %(message)s",
)


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def _read_version() -> str:
    """从 pyproject.toml 读取版本号。"""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject.read_text())
        if match:
            return match.group(1)
    return "0.0.0"


VERSION = _read_version()
app = FastAPI(title="NfoFetch", version=VERSION)

create_rate_limit_middleware(app)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _jinja_escapejs(value: str) -> str:
    """Jinja2 过滤器：转义字符串中的特殊字符以安全嵌入 JavaScript 字符串（单引号上下文）。"""
    return (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


templates.env.filters["escapejs"] = _jinja_escapejs

# 后台刮削任务进度存储（内存）
scrape_tasks: dict[str, dict[str, Any]] = {}
scrape_tasks_lock = threading.Lock()


def _update_task(task_id: str, **kwargs: Any) -> None:
    with scrape_tasks_lock:
        if task_id in scrape_tasks:
            scrape_tasks[task_id].update(kwargs)


def _cleanup_stale_tasks(max_age: float = 300.0) -> None:
    """移除超过 max_age 秒的已完成任务，防止内存泄漏。"""
    now = time.monotonic()
    with scrape_tasks_lock:
        stale = [
            tid
            for tid, t in scrape_tasks.items()
            if t.get("done") and (now - t.get("created_at", 0)) > max_age
        ]
        for tid in stale:
            scrape_tasks.pop(tid, None)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """首页：渲染包含 HTMX 表单的页面。"""
    return templates.TemplateResponse(
        request, "index.html", {"request": request, "version": VERSION}
    )


def _natural_sort_key(s: str) -> tuple[Any, ...]:
    """将字符串拆分为文本和数字部分，用于自然排序（\"movie 2\" < \"movie 10\"）。"""
    parts = re.split(r"(\d+)", s.lower())
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts)


def _sort_browser_entries(
    entries: list[dict[str, Any]],
    sort_by: str,
    sort_order: str,
) -> None:
    """对文件浏览器条目排序，目录始终排在文件前。"""
    reverse = sort_order == "desc"

    def _sort_key(e: dict[str, Any]) -> Any:
        if sort_by == "natural":
            return _natural_sort_key(e["name"].rstrip("/"))
        if sort_by == "mtime":
            return e.get("mtime", 0.0)
        return e["name_lower"]

    entries.sort(key=_sort_key, reverse=reverse)
    # 稳定排序保证目录在前（不改变同组内排好的顺序）
    entries.sort(key=lambda e: 0 if e["is_dir"] else 1)


@app.get("/browse", response_class=HTMLResponse)
async def browse(
    request: Request,
    path: str | None = Query(default=None, description="要浏览的起始路径"),
    sort_by: str = Query(
        default="name", description="排序方式：name / natural / mtime"
    ),
    sort_order: str = Query(default="asc", description="排序方向：asc / desc"),
) -> HTMLResponse:
    """简单的服务器文件浏览：用于选择本地视频文件路径。

    为了安全，浏览范围限制在 NFOFETCH_BROWSE_ROOT（默认当前工作目录）下。
    """
    base_dir = Path(os.getenv("NFOFETCH_BROWSE_ROOT", os.getcwd())).resolve()

    if path:
        current = Path(path).expanduser()
    else:
        current = base_dir

    try:
        current = current.resolve()
    except OSError:
        current = base_dir

    # 不允许跳出 base_dir 之外
    try:
        current.relative_to(base_dir)
    except ValueError:
        current = base_dir

    parent_dir: str | None = None
    if current != base_dir:
        parent_dir = str(current.parent)

    entries: list[dict[str, Any]] = []
    try:
        # FUSE 下先 stat 目录，尝试触发 rclone 缓存刷新
        current.stat()
    except OSError:
        pass
    try:
        with os.scandir(current) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                is_dir = entry.is_dir()
                is_file = entry.is_file()
                if not (is_dir or is_file):
                    continue
                entry_dict: dict[str, Any] = {
                    "name": entry.name + ("/" if is_dir else ""),
                    "name_lower": entry.name.lower(),
                    "path": entry.path,
                    "is_dir": is_dir,
                    "is_video": is_file
                    and Path(entry.name).suffix.lower() in VIDEO_EXTENSIONS,
                }
                if sort_by == "mtime":
                    try:
                        entry_dict["mtime"] = entry.stat().st_mtime
                    except OSError:
                        entry_dict["mtime"] = 0.0
                entries.append(entry_dict)
    except OSError:
        # 目录不可读时，返回空列表
        entries = []

    _sort_browser_entries(entries, sort_by, sort_order)

    return templates.TemplateResponse(
        request,
        "partials/file_browser.html",
        {
            "request": request,
            "current_dir": str(current),
            "parent_dir": parent_dir,
            "entries": entries,
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
    )


@app.post("/browse/delete")
async def browse_delete(path: str = Form(...)) -> dict[str, bool]:
    """删除文件或空目录，路径必须在 NFOFETCH_BROWSE_ROOT 范围内。"""
    base_dir = Path(os.getenv("NFOFETCH_BROWSE_ROOT", os.getcwd())).resolve()

    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(base_dir)
    except ValueError:
        return {"ok": False}
    if not target.exists():
        return {"ok": False}
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError:
        return {"ok": False}
    return {"ok": True}


@app.post("/scrape/fetch", response_class=HTMLResponse)
async def scrape_fetch(
    request: Request,
    url: str = Form(...),
    video_path: str | None = Form(default=None),
    search_poster_url: str | None = Form(default=None),
) -> HTMLResponse:
    """仅刮削元数据和图片，不写入磁盘。返回预览供用户选择后点击「写入」。

    支持两种输入：
    - URL：直接刮取该 URL 的元数据
    - 番号/关键字：先搜索影片，用户选择后再刮取
    """
    settings = get_settings()
    error: str | None = None
    metadata = None
    poster_candidates: list[str] = []

    metadata_b64: str | None = None
    if is_url(url):
        try:
            metadata = scrape_movie(url, settings=settings)
            seen: set[str] = set()
            for u in list(metadata.posters) + list(metadata.art):
                s = str(u)
                if s not in seen:
                    seen.add(s)
                    poster_candidates.append(s)
            if search_poster_url and search_poster_url not in seen:
                poster_candidates.append(search_poster_url)
                seen.add(search_poster_url)
            metadata_b64 = base64.b64encode(
                metadata.model_dump_json().encode()
            ).decode()
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    else:
        return await search_and_select(request, url, video_path=video_path)

    return templates.TemplateResponse(
        request,
        "partials/scrape_preview.html",
        {
            "request": request,
            "metadata": metadata,
            "metadata_b64": metadata_b64,
            "poster_candidates": poster_candidates,
            "error": error,
            "url": url,
            "video_path": video_path,
        },
    )


@app.post("/scrape/search", response_class=HTMLResponse)
async def search_and_select(
    request: Request,
    query: str = Form(...),
    video_path: str | None = None,
) -> HTMLResponse:
    """搜索影片并显示结果列表供用户选择。"""
    settings = get_settings()
    error: str | None = None
    results: list = []

    try:
        results = search_movie(query, settings=settings)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    return templates.TemplateResponse(
        request,
        "partials/search_results.html",
        {
            "request": request,
            "results": results,
            "error": error,
            "query": query,
            "video_path": video_path,
        },
    )


@app.post("/api/scrape-task")
async def create_scrape_task() -> dict[str, str]:
    """创建刮削任务，返回 task_id。"""
    _cleanup_stale_tasks()
    task_id = str(uuid.uuid4())
    scrape_tasks[task_id] = {
        "phase": "preparing",
        "current": 0,
        "total": 0,
        "detail": "正在准备…",
        "done": False,
        "error": None,
        "created_at": time.monotonic(),
    }
    return {"task_id": task_id}


@app.post("/scrape", response_class=HTMLResponse)
async def scrape(
    request: Request,
    url: str = Form(...),
    video_path: str = Form(...),
    poster_url: str | None = Form(default=None),
    fanart_url: str | None = Form(default=None),
    crop_direction: str = Form(default="none"),
    rename_format: str | None = Form(default=None),
    rename_dir: str | None = Form(default=None),
    download_concurrency: int = Form(default=4),
    task_id: str = Form(default=""),
    metadata_b64: str | None = Form(default=None),
) -> HTMLResponse:
    """在线程池中执行刮削写入（阻塞），实时通过 task_id 更新进度。

    优先使用前端传回的 metadata_b64（预览时已抓取），避免重复 HTTP 请求。
    """
    settings = get_settings()
    if task_id:
        _update_task(task_id, phase="preparing", current=0, total=0, detail="正在准备…")

    try:
        if metadata_b64:
            metadata = MovieMetadata.model_validate_json(
                base64.b64decode(metadata_b64.encode()).decode()
            )
        else:
            metadata = scrape_movie(url, settings=settings)
        nfo_text = build_movie_nfo(metadata)

        vp = Path(video_path).expanduser()
        if not vp.is_file():
            raise FileNotFoundError(f"视频文件不存在或不可读：{vp}")

        base_dir = Path(os.getenv("NFOFETCH_BROWSE_ROOT", os.getcwd())).resolve()
        try:
            vp.absolute().relative_to(base_dir)
        except ValueError:
            raise PermissionError(f"视频路径超出允许范围：{vp}")

        def on_progress(phase: str, current: int, total: int, detail: str) -> None:
            if task_id:
                _update_task(
                    task_id, phase=phase, current=current, total=total, detail=detail
                )

        # 在线程池中执行阻塞 I/O，避免阻塞事件循环（Issue 7）
        loop = asyncio.get_running_loop()
        func = functools.partial(
            save_assets_for_existing_video,
            metadata=metadata,
            nfo_text=nfo_text,
            video_path=vp,
            settings=settings,
            max_extra_images=settings.max_extra_images,
            poster_url=poster_url,
            fanart_url=fanart_url,
            crop_direction=crop_direction,
            rename_format=rename_format or None,
            rename_dir=rename_dir or None,
            download_concurrency=download_concurrency,
            http_timeout=settings.http_timeout,
            batch_timeout=settings.batch_timeout,
            on_progress=on_progress,
        )
        result: ScrapeResult = await loop.run_in_executor(None, func)
    except Exception as exc:  # noqa: BLE001 - 用户侧希望看到原始错误
        result = ScrapeResult(success=False, message=str(exc))
    finally:
        if task_id:
            _update_task(task_id, done=True)

    # 刮削成功后更新文件浏览器记住的路径，使下次打开时定位到新目录
    if result.success and result.movie_dir:
        try:
            current = load_user_settings()
            current.last_browse_path = result.movie_dir
            save_user_settings(current)
        except Exception:
            pass

    return templates.TemplateResponse(
        request,
        "partials/scrape_result.html",
        {
            "request": request,
            "result": result,
        },
    )


@app.get("/api/settings", response_model=UserSettings)
async def api_get_settings() -> UserSettings:
    """获取持久化的用户设置。"""
    return load_user_settings()


@app.post("/api/settings")
async def api_update_settings(settings: UserSettings) -> dict[str, bool]:
    """保存用户设置到 JSON 文件（只合并请求中携带的字段）。"""
    current = load_user_settings()
    # 注意：exclude_unset=True 意味着前端传 false 的 bool 字段会被忽略，
    # 导致用户无法关闭开关。当前 UserSettings 无 bool 字段，暂无此问题。
    updated = current.model_copy(update=settings.model_dump(exclude_unset=True))
    save_user_settings(updated)
    return {"ok": True}


# 内置重命名格式预设
_BUILT_IN_PRESETS: dict[str, Preset] = {
    "VR": Preset(
        rename_format="{id}-{resolution}-{idx}_{vr}",
        rename_dir="[{actor:3}][{date}]{id}-{resolution}",
    ),
    "非VR": Preset(
        rename_format="{id}-{resolution}-{idx}",
        rename_dir="[{actor:3}][{date}]{id}-{resolution}",
    ),
}


@app.get("/api/presets")
async def api_get_presets() -> dict[str, dict[str, Preset]]:
    """返回内置 + 用户自定义预设。"""
    user = load_user_settings()
    return {"built_in": _BUILT_IN_PRESETS, "user": user.presets}


@app.post("/api/presets")
async def api_save_preset(
    name: str = Form(...), rename_format: str = Form(""), rename_dir: str = ""
) -> dict[str, bool]:
    """保存或覆盖一个用户预设。"""
    settings = load_user_settings()
    settings.presets[name] = Preset(rename_format=rename_format, rename_dir=rename_dir)
    save_user_settings(settings)
    return {"ok": True}


@app.delete("/api/presets")
async def api_delete_preset(name: str = Query(...)) -> dict[str, bool]:
    """删除一个用户预设。"""
    settings = load_user_settings()
    settings.presets.pop(name, None)
    save_user_settings(settings)
    return {"ok": True}


@app.get("/api/scrape-task/{task_id}")
async def get_scrape_task(task_id: str) -> dict[str, Any]:
    """返回刮削任务当前进度。"""
    task = scrape_tasks.get(task_id)
    if task is None:
        return {"error": "任务不存在", "done": True}
    return {
        "phase": task.get("phase", ""),
        "current": task.get("current", 0),
        "total": task.get("total", 0),
        "detail": task.get("detail", ""),
        "done": task.get("done", False),
    }


@app.get("/health", response_class=HTMLResponse)
async def health() -> HTMLResponse:
    return HTMLResponse("OK")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
