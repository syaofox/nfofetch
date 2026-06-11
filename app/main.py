import asyncio
import functools
import logging
import os
import re
from pathlib import Path

from fastapi import FastAPI, Form, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.middleware import create_rate_limit_middleware
from app.schemas import ScrapeResult, UserSettings
from app.services.file_service import VIDEO_EXTENSIONS, save_assets_for_existing_video
from app.services.nfo_service import build_movie_nfo
from app.services.scrape_service import is_url, scrape_movie, search_movie
from app.services.settings_service import load_user_settings, save_user_settings

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """首页：渲染包含 HTMX 表单的页面。"""
    return templates.TemplateResponse(
        request, "index.html", {"request": request, "version": VERSION}
    )


@app.get("/browse", response_class=HTMLResponse)
async def browse(
    request: Request,
    path: str | None = Query(default=None, description="要浏览的起始路径"),
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

    entries: list[dict[str, str | bool]] = []
    try:
        for child in sorted(
            current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
        ):
            if child.name.startswith("."):
                continue
            if not (child.is_dir() or child.is_file()):
                continue
            if child.is_file() and child.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            entries.append(
                {
                    "name": child.name + ("/" if child.is_dir() else ""),
                    "path": str(child),
                    "is_dir": child.is_dir(),
                }
            )
    except OSError:
        # 目录不可读时，返回空列表
        entries = []

    return templates.TemplateResponse(
        request,
        "partials/file_browser.html",
        {
            "request": request,
            "current_dir": str(current),
            "parent_dir": parent_dir,
            "entries": entries,
        },
    )


@app.post("/scrape/fetch", response_class=HTMLResponse)
async def scrape_fetch(
    request: Request,
    url: str = Form(...),
    video_path: str | None = Form(default=None),
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

    if is_url(url):
        try:
            metadata = scrape_movie(url, settings=settings)
            seen: set[str] = set()
            for u in list(metadata.posters) + list(metadata.art):
                s = str(u)
                if s not in seen:
                    seen.add(s)
                    poster_candidates.append(s)
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


@app.post("/scrape", response_class=HTMLResponse)
async def scrape(
    request: Request,
    url: str = Form(...),
    video_path: str = Form(...),
    poster_url: str | None = Form(default=None),
    fanart_url: str | None = Form(default=None),
    rename_format: str | None = Form(default=None),
    download_concurrency: int = Form(default=4),
) -> HTMLResponse:
    """处理 HTMX 表单：刮削 javdb 并生成 NFO / 图片 / 影片目录。"""
    settings = get_settings()
    try:
        metadata = scrape_movie(url, settings=settings)
        nfo_text = build_movie_nfo(metadata)

        vp = Path(video_path).expanduser()
        if not vp.is_file():
            raise FileNotFoundError(f"视频文件不存在或不可读：{vp}")

        # 在线程池中执行阻塞 I/O 操作，避免阻塞事件循环（Issue 7）
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
            rename_format=rename_format or None,
            download_concurrency=download_concurrency,
            http_timeout=settings.http_timeout,
            batch_timeout=settings.batch_timeout,
        )
        result: ScrapeResult = await loop.run_in_executor(None, func)
    except Exception as exc:  # noqa: BLE001 - 用户侧希望看到原始错误
        result = ScrapeResult(success=False, message=str(exc))

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
    updated = current.model_copy(update=settings.model_dump(exclude_unset=True))
    save_user_settings(updated)
    return {"ok": True}


@app.get("/health", response_class=HTMLResponse)
async def health() -> HTMLResponse:
    return HTMLResponse("OK")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
