from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl


class Actor(BaseModel):
    """演员信息。"""

    name: str
    role: Optional[str] = None
    thumb: Optional[HttpUrl] = None


class MovieMetadata(BaseModel):
    """统一的影片元数据模型，供各站点 scraper 输出。"""

    title: str = Field(..., description="主标题，例如 `ABP-123 我的女友`")
    original_title: Optional[str] = Field(
        default=None, description="原始标题 / 日文标题，可选"
    )
    number: Optional[str] = Field(default=None, description="番号 / 识别码")
    plot: Optional[str] = None
    year: Optional[int] = None
    premiered: Optional[str] = Field(
        default=None, description="首发日期，建议使用 YYYY-MM-DD"
    )
    releasedate: Optional[str] = Field(
        default=None, description="发行日期，YYYY-MM-DD，可与 premiered 相同"
    )
    runtime: Optional[int] = Field(
        default=None, description="片长，单位分钟，无法确定时可以为 None"
    )

    genres: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    actors: List[Actor] = Field(default_factory=list)

    # 制作信息
    studio: Optional[str] = None
    label: Optional[str] = None
    series: Optional[str] = None
    directors: List[str] = Field(
        default_factory=list, description="导演列表，可能多名导演"
    )
    rating: Optional[float] = Field(
        default=None, description="评分（0-10 之间），无法解析时为 None"
    )

    posters: List[HttpUrl] = Field(
        default_factory=list, description="封面图片 URL 列表，优先第一张"
    )
    art: List[HttpUrl] = Field(
        default_factory=list, description="背景图 / 剧照 URL 列表"
    )

    source_url: Optional[HttpUrl] = Field(
        default=None, description="原始站点页面 URL，便于溯源"
    )


class ScrapeResult(BaseModel):
    """一次完整刮削的结果，用于返回到模板做展示。"""

    success: bool = True
    message: Optional[str] = None

    metadata: Optional[MovieMetadata] = None

    movie_dir: Optional[str] = None
    nfo_path: Optional[str] = None
    video_path: Optional[str] = None
    poster_path: Optional[str] = None
    fanart_path: Optional[str] = None
    extra_images: List[str] = Field(default_factory=list)

    # 前端选择的封面 / 背景图源 URL，用于预览展示。
    chosen_poster_url: Optional[str] = None
    chosen_fanart_url: Optional[str] = None

