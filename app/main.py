from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.schemas import ScrapeResult
from app.services.file_service import save_assets_for_existing_video
from app.services.nfo_service import build_movie_nfo
from app.services.scrape_service import scrape_movie


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


app = FastAPI(title="NfoFetch", version="0.1.0")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """首页：渲染包含 HTMX 表单的页面。"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/scrape", response_class=HTMLResponse)
async def scrape(
    request: Request,
    url: str = Form(...),
    video_path: str = Form(...),
    poster_url: str | None = Form(default=None),
    fanart_url: str | None = Form(default=None),
) -> HTMLResponse:
    """处理 HTMX 表单：刮削 javdb 并生成 NFO / 图片 / 影片目录。"""
    settings = get_settings()
    try:
        metadata = scrape_movie(url, settings=settings)
        nfo_text = build_movie_nfo(metadata)

        vp = Path(video_path).expanduser()
        if not vp.is_file():
            raise FileNotFoundError(f"视频文件不存在或不可读：{vp}")

        result: ScrapeResult = save_assets_for_existing_video(
            metadata=metadata,
            nfo_text=nfo_text,
            video_path=vp,
            settings=settings,
            poster_url=poster_url,
            fanart_url=fanart_url,
        )
    except Exception as exc:  # noqa: BLE001 - 用户侧希望看到原始错误
        result = ScrapeResult(success=False, message=str(exc))

    return templates.TemplateResponse(
        "partials/scrape_result.html",
        {
            "request": request,
            "result": result,
        },
    )


@app.post("/scrape/preview", response_class=HTMLResponse)
async def scrape_preview(
    request: Request,
    url: str = Form(...),
) -> HTMLResponse:
    """仅根据 URL 抓取元数据，返回图片候选列表供前端选择 poster / fanart。"""
    settings = get_settings()
    error: str | None = None
    poster_candidates: list[str] = []

    try:
        metadata = scrape_movie(url, settings=settings)
        seen: set[str] = set()
        # 优先封面列表，其次剧照列表，统一去重。
        for u in list(metadata.posters) + list(metadata.art):
            s = str(u)
            if s not in seen:
                seen.add(s)
                poster_candidates.append(s)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    return templates.TemplateResponse(
        "partials/image_options.html",
        {
            "request": request,
            "poster_candidates": poster_candidates,
            "error": error,
        },
    )


@app.get("/health", response_class=HTMLResponse)
async def health() -> HTMLResponse:
    return HTMLResponse("OK")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

