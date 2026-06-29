from __future__ import annotations

import asyncio
import base64
import dataclasses
import functools
import logging
import urllib.parse
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import tempfile
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.middleware import create_rate_limit_middleware
from app.schemas import MovieMetadata, Preset, ScrapeResult, UserSettings
from app.services.file_service import find_local_images, save_assets_for_existing_video
from app.services.file_utils import VIDEO_EXTENSIONS
from app.services.nfo_service import build_movie_nfo
from app.services.scrape_service import is_url, scrape_movie, search_movie
from app.services.settings_service import load_user_settings, save_user_settings

logger = logging.getLogger(__name__)

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
templates.env.filters["urlencode"] = urllib.parse.quote

# 后台刮削任务进度存储（内存）
MAX_SCRAPE_TASKS = 50
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
        logger.warning("stat 失败: %s", current)
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


@app.get("/api/crop-image")
async def api_crop_image(
    url: str = Query(...),
    auto_trim: bool = Query(default=False),
) -> Response:
    """下载远程图片，可选裁白边后返回，供前端裁切预览。

    用于精确裁切弹窗中展示图片（避免 CORS 问题，并支持 auto_trim 预处理）。
    """
    settings = get_settings()
    settings = _merge_ui_settings(settings)
    from app.services.image_utils import _download_to_temp

    tmp = _download_to_temp(url, settings)
    if tmp is None:
        raise HTTPException(status_code=502, detail="下载图片失败")
    try:
        if auto_trim:
            from app.services.image_utils import _trim_white_borders

            _trim_white_borders(tmp)
        content = tmp.read_bytes()
        ext = tmp.suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(ext, "application/octet-stream")
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"},
        )
    finally:
        tmp.unlink(missing_ok=True)


ALLOWED_UPLOAD_EXTENSIONS: set = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_SIZE: int = 20 * 1024 * 1024  # 20 MB


def _cleanup_uploaded(*paths: str | None) -> None:
    """清理上传的临时文件（写入后删除）。"""
    for p in paths:
        if p:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                logger.warning("清理上传文件失败: %s", p)


_UPLOAD_PREFIX = "._nfofetch_upload_"


@app.post("/api/upload-image")
async def api_upload_image(file: UploadFile = File(...)) -> dict[str, str]:
    """上传用户自定义图片，保存到 /tmp 并返回本地路径。

    支持的文件类型: jpg/jpeg/png/webp，大小限制 20MB。
    上传文件放在系统临时目录，避免对 FUSE 产生额外写入压力。
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="仅支持图片文件上传")

    suffix = (Path(file.filename or "image.jpg").suffix or ".jpg").lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片格式: {suffix}，仅支持 jpg/png/webp",
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="图片大小超过 20MB 限制")

    tmp = tempfile.NamedTemporaryFile(
        suffix=suffix, prefix=_UPLOAD_PREFIX, delete=False
    )
    tmp_path = Path(tmp.name)
    tmp.close()
    tmp_path.write_bytes(content)
    logger.info("上传自定义图片: %s (%d bytes)", tmp_path, len(content))

    serve_url = f"/api/uploaded-image?path={tmp_path}"
    return {"path": str(tmp_path), "serve_url": serve_url}


@app.get("/api/uploaded-image")
async def serve_uploaded_image(path: str = Query(...)) -> Response:
    """服务上传到 /tmp 的预览图片（含安全校验）。"""
    target = Path(path).resolve()
    tmp_dir = Path(tempfile.gettempdir()).resolve()
    if not str(target).startswith(str(tmp_dir)):
        raise HTTPException(status_code=403, detail="路径不在临时目录内")
    if _UPLOAD_PREFIX not in target.name:
        raise HTTPException(status_code=403, detail="非法的上传文件")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    content = target.read_bytes()
    ext = target.suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"},
    )


# 向后兼容旧端点
@app.post("/api/upload-poster")
async def api_upload_poster(file: UploadFile = File(...)) -> dict[str, str]:
    """向后兼容: 委托给 /api/upload-image。"""
    return await api_upload_image(file=file)


@app.get("/file")
async def serve_file(path: str = Query(...)) -> FileResponse:
    """服务本地图片文件，路径必须在 NFOFETCH_BROWSE_ROOT 范围内。"""
    base_dir = Path(os.getenv("NFOFETCH_BROWSE_ROOT", os.getcwd())).resolve()
    target = (base_dir / path).resolve()
    try:
        target.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径不在允许范围内")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target)


@app.get("/api/local-image")
async def serve_local_image(path: str = Query(...)) -> Response:
    """服务视频同目录的本地图片，用于刮削预览展示。

    路径必须在 NFOFETCH_BROWSE_ROOT 范围内。
    使用 absolute() 而非 resolve() 以避免触发 FUSE 网络 stat。
    """
    base_dir = Path(os.getenv("NFOFETCH_BROWSE_ROOT", os.getcwd())).absolute()
    target = Path(path).absolute()
    try:
        target.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径不在允许范围内")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    content = target.read_bytes()
    ext = target.suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"},
    )


def _merge_ui_settings(settings: Settings) -> Settings:
    """从 UserSettings 合并 UI 设置（优先于环境变量），返回新的 Settings 实例。

    原始 settings 不会被修改，保证线程安全。
    """
    try:
        user = load_user_settings()
        kwargs: dict[str, Any] = {}
        if user.javdb_cookie:
            kwargs["javdb_cookie"] = user.javdb_cookie
        if user.jav321_cookie:
            kwargs["jav321_cookie"] = user.jav321_cookie
        if user.dmm_cookie:
            kwargs["dmm_cookie"] = user.dmm_cookie
        if user.serial_writes is not None:
            kwargs["serial_writes"] = user.serial_writes
        if user.lock_enabled is not None:
            kwargs["lock_enabled"] = user.lock_enabled
        if user.write_delay is not None:
            kwargs["write_delay"] = user.write_delay
        if user.max_extra_images is not None:
            kwargs["max_extra_images"] = user.max_extra_images
        if user.delete_orphan_extrafanart is not None:
            kwargs["delete_orphan_extrafanart"] = user.delete_orphan_extrafanart
            logger.info(
                "UI 设置: delete_orphan_extrafanart=%s",
                user.delete_orphan_extrafanart,
            )
        if user.filter_actor_gender is not None:
            kwargs["filter_actor_gender"] = user.filter_actor_gender
            logger.info(
                "UI 设置: filter_actor_gender=%s",
                user.filter_actor_gender,
            )
        if user.download_concurrency is not None:
            kwargs["download_concurrency"] = user.download_concurrency
            logger.info(
                "UI 设置: download_concurrency=%s",
                user.download_concurrency,
            )
        if user.auto_trim_white_borders is not None:
            kwargs["auto_trim_white_borders"] = user.auto_trim_white_borders
            logger.info(
                "UI 设置: auto_trim_white_borders=%s",
                user.auto_trim_white_borders,
            )
        if user.enabled_scrapers is not None:
            kwargs["enabled_scrapers"] = set(user.enabled_scrapers)
            logger.info(
                "UI 设置: enabled_scrapers=%s",
                user.enabled_scrapers,
            )
        return dataclasses.replace(settings, **kwargs)
    except Exception:
        logger.warning("合并 UI 设置失败", exc_info=True)
        return settings


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
    settings = _merge_ui_settings(settings)
    error: str | None = None
    metadata = None
    poster_candidates: list[str] = []
    local_image_map: dict[str, str] = {}

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

    # 扫描视频同目录的本地图片
    if video_path:
        for img_path in find_local_images(Path(video_path)):
            serve_url = f"/api/local-image?path={urllib.parse.quote(img_path)}"
            poster_candidates.append(serve_url)
            local_image_map[serve_url] = img_path

    parsed_url = urllib.parse.urlparse(url)
    default_poster_first = "jav321" in parsed_url.netloc.lower()

    return templates.TemplateResponse(
        request,
        "partials/scrape_preview.html",
        {
            "request": request,
            "metadata": metadata,
            "metadata_b64": metadata_b64,
            "poster_candidates": poster_candidates,
            "local_image_map": local_image_map,
            "error": error,
            "url": url,
            "video_path": video_path,
            "default_poster_first": default_poster_first,
            "default_move_to_subdir": load_user_settings().move_to_subdir or False,
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
    settings = _merge_ui_settings(settings)
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
    with scrape_tasks_lock:
        active = sum(1 for t in scrape_tasks.values() if not t.get("done"))
        if active >= MAX_SCRAPE_TASKS:
            raise HTTPException(
                status_code=503,
                detail=f"刮削任务队列已满（上限 {MAX_SCRAPE_TASKS}），请等待当前任务完成",
            )
    task_id = str(uuid.uuid4())
    with scrape_tasks_lock:
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
    crop_x: int = Form(default=0),
    crop_y: int = Form(default=0),
    crop_w: int = Form(default=0),
    crop_h: int = Form(default=0),
    custom_poster_path: str | None = Form(default=None),
    custom_fanart_path: str | None = Form(default=None),
    move_to_subdir: bool = Form(default=False),
    rename_format: str | None = Form(default=None),
    rename_dir: str | None = Form(default=None),
    task_id: str = Form(default=""),
    metadata_b64: str | None = Form(default=None),
) -> HTMLResponse:
    """在线程池中执行刮削写入（阻塞），实时通过 task_id 更新进度。

    优先使用前端传回的 metadata_b64（预览时已抓取），避免重复 HTTP 请求。
    """
    settings = get_settings()
    settings = _merge_ui_settings(settings)
    if task_id:
        _update_task(task_id, phase="preparing", current=0, total=0, detail="正在准备…")

    try:
        if metadata_b64:
            metadata = MovieMetadata.model_validate_json(
                base64.b64decode(metadata_b64.encode()).decode()
            )
        else:
            logger.warning(
                "metadata_b64 缺失，需要重新刮取 URL（可能使用了过期的预览缓存）: %s",
                url,
            )
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

        # 将本地图片 serve URL 转回文件路径，_download_to_temp 可直接读取
        if poster_url and poster_url.startswith("/api/local-image?path="):
            poster_url = urllib.parse.parse_qs(urllib.parse.urlparse(poster_url).query)[
                "path"
            ][0]
        if fanart_url and fanart_url.startswith("/api/local-image?path="):
            fanart_url = urllib.parse.parse_qs(urllib.parse.urlparse(fanart_url).query)[
                "path"
            ][0]

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
            crop_box=(crop_x, crop_y, crop_w, crop_h)
            if crop_w > 0 and crop_h > 0
            else None,
            custom_poster_path=custom_poster_path,
            custom_fanart_path=custom_fanart_path,
            move_to_subdir=move_to_subdir,
            rename_format=rename_format or None,
            rename_dir=rename_dir or None,
            download_concurrency=settings.download_concurrency,
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

    # 写入完成后清理上传的临时文件
    _cleanup_uploaded(custom_poster_path, custom_fanart_path)

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


@app.post("/api/rename-preview")
async def rename_preview(
    video_path: str = Form(...),
    rename_format: str | None = Form(default=None),
    move_to_subdir: bool = Form(default=False),
) -> dict:
    """预览重命名：返回受 rename_format 影响的视频文件数。"""
    from app.services.rename_utils import _count_files_to_rename

    video = Path(video_path)
    if not video.exists():
        return {"count": 0}
    count = _count_files_to_rename(video, rename_format, move_to_subdir=move_to_subdir)
    return {"count": count}


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
