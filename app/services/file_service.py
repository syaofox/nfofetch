from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import UploadFile

from app.config import Settings
from app.schemas import MovieMetadata, ScrapeResult


def sanitize_filename(name: str) -> str:
    """简易文件名清洗，移除常见非法字符。"""
    invalid = '<>:"/\\\\|?*'
    cleaned = "".join("_" if ch in invalid else ch for ch in name)
    return cleaned.strip() or "movie"


def build_movie_dir_name(metadata: MovieMetadata, upload_file: UploadFile) -> str:
    stem = Path(upload_file.filename or "movie").stem
    parts: List[str] = []
    if metadata.number:
        parts.append(metadata.number)
    if metadata.title and metadata.title not in parts:
        parts.append(metadata.title)
    base = " ".join(parts) if parts else stem
    return sanitize_filename(base)


def save_movie_package(
    *,
    metadata: MovieMetadata,
    nfo_text: str,
    upload_file: UploadFile,
    settings: Settings,
    max_extra_images: int = 8,
) -> ScrapeResult:
    """保存 NFO、视频文件和图片到目标目录，返回 ScrapeResult 用于前端展示。"""

    movie_dir_name = build_movie_dir_name(metadata, upload_file)
    movie_dir = settings.output_root / movie_dir_name
    movie_dir.mkdir(parents=True, exist_ok=True)

    # 保存视频文件（直接保存上传内容）
    suffix = Path(upload_file.filename or "movie.mp4").suffix or ".mp4"
    video_path = movie_dir / f"{movie_dir_name}{suffix}"
    with video_path.open("wb") as f:
        shutil.copyfileobj(upload_file.file, f)

    # 写入 movie.nfo
    nfo_path = movie_dir / "movie.nfo"
    with nfo_path.open("w", encoding="utf-8") as f:
        f.write(nfo_text)

    # 下载图片
    poster_path: Optional[Path] = None
    fanart_path: Optional[Path] = None
    extra_paths: List[Path] = []

    poster_urls = list(metadata.posters)
    art_urls = list(metadata.art)

    def download_image(url: str, dest: Path) -> bool:
        try:
            # httpx 1.x 不再支持 proxies 关键字，这里通过环境变量传递代理。
            if settings.http_proxy:
                os.environ.setdefault("HTTP_PROXY", settings.http_proxy)
                os.environ.setdefault("HTTPS_PROXY", settings.http_proxy)

            with httpx.Client(
                headers={"User-Agent": settings.user_agent},
                timeout=20.0,
            ) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with dest.open("wb") as f:
                        for chunk in resp.iter_bytes():
                            f.write(chunk)
            return True
        except Exception:
            return False

    # 1. poster.jpg
    if poster_urls:
        poster_path = movie_dir / "poster.jpg"
        if not download_image(str(poster_urls[0]), poster_path):
            poster_path = None

    # 2. fanart.jpg
    fanart_candidates: List[str] = []
    if art_urls:
        fanart_candidates.append(str(art_urls[0]))
    if poster_urls:
        fanart_candidates.append(str(poster_urls[0]))

    for url in fanart_candidates:
        fanart_path_candidate = movie_dir / "fanart.jpg"
        if download_image(url, fanart_path_candidate):
            fanart_path = fanart_path_candidate
            break

    # 3. extrafanart/*
    extra_dir = movie_dir / "extrafanart"
    extra_dir.mkdir(exist_ok=True)
    used_urls = set()
    if poster_urls:
        used_urls.add(str(poster_urls[0]))
    if art_urls:
        used_urls.add(str(art_urls[0]))

    all_extra_sources: List[str] = []
    all_extra_sources.extend(str(u) for u in art_urls)
    all_extra_sources.extend(str(u) for u in poster_urls)

    idx = 1
    for url in all_extra_sources:
        if url in used_urls:
            continue
        if idx > max_extra_images:
            break
        dest = extra_dir / f"{idx:02d}.jpg"
        if download_image(url, dest):
            extra_paths.append(dest)
            idx += 1

    return ScrapeResult(
        success=True,
        message=None,
        metadata=metadata,
        movie_dir=str(movie_dir),
        nfo_path=str(nfo_path),
        video_path=str(video_path),
        poster_path=str(poster_path) if poster_path else None,
        fanart_path=str(fanart_path) if fanart_path else None,
        extra_images=[str(p) for p in extra_paths],
    )

