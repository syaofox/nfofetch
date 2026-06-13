from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class Actor(BaseModel):
    """演员信息。"""

    name: str
    role: str | None = None
    thumb: HttpUrl | None = None


class MovieMetadata(BaseModel):
    """统一的影片元数据模型，供各站点 scraper 输出。"""

    title: str = Field(..., description="主标题，例如 `ABP-123 我的女友`")
    original_title: str | None = Field(
        default=None, description="原始标题 / 日文标题，可选"
    )
    number: str | None = Field(default=None, description="番号 / 识别码")
    plot: str | None = None
    year: int | None = None
    premiered: str | None = Field(
        default=None, description="首发日期，建议使用 YYYY-MM-DD"
    )
    releasedate: str | None = Field(
        default=None, description="发行日期，YYYY-MM-DD，可与 premiered 相同"
    )
    runtime: int | None = Field(
        default=None, description="片长，单位分钟，无法确定时可以为 None"
    )

    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    actors: list[Actor] = Field(default_factory=list)

    # 制作信息
    studio: str | None = None
    label: str | None = None
    series: str | None = None
    directors: list[str] = Field(
        default_factory=list, description="导演列表，可能多名导演"
    )
    rating: float | None = Field(
        default=None, description="评分（0-10 之间），无法解析时为 None"
    )

    posters: list[HttpUrl] = Field(
        default_factory=list, description="封面图片 URL 列表，优先第一张"
    )
    art: list[HttpUrl] = Field(
        default_factory=list, description="背景图 / 剧照 URL 列表"
    )

    source_url: HttpUrl | None = Field(
        default=None, description="原始站点页面 URL，便于溯源"
    )


class SearchResult(BaseModel):
    """搜索结果模型"""

    title: str
    number: str | None = None
    url: str
    poster_url: str | None = None
    date: str | None = None


class ScrapeResult(BaseModel):
    """一次完整刮削的结果，用于返回到模板做展示。"""

    success: bool = True
    message: str | None = None

    metadata: MovieMetadata | None = None

    movie_dir: str | None = None
    nfo_path: str | None = None
    video_path: str | None = None
    poster_path: str | None = None
    fanart_path: str | None = None
    extra_images: list[str] = Field(default_factory=list)

    # 前端选择的封面 / 背景图源 URL，用于预览展示。
    chosen_poster_url: str | None = None
    chosen_fanart_url: str | None = None


class UserSettings(BaseModel):
    """用户偏好设置，持久化到 JSON 文件。"""

    rename_format: str = "[{actor}][{date}]{id}"
    rename_dir: str = ""
    last_browse_path: str = ""
    download_concurrency: int = 4
