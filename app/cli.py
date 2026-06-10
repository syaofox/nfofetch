from __future__ import annotations

import argparse
from pathlib import Path

from app.config import get_settings
from app.services.nfo_service import build_movie_nfo
from app.services.scrape_service import scrape_movie
from app.services.file_service import (
    DEFAULT_RENAME_FORMAT,
    save_assets_for_existing_video,
)


def main(argv: list[str] | None = None) -> None:
    """命令行入口：

    根据 javdb 影片页面 URL 和本地已存在的视频文件，在该视频所在目录
    生成 Jellyfin 兼容的 movie.nfo、poster.jpg、fanart.jpg、extrafanart/* 等文件，
    不会复制或移动原视频文件。
    """

    parser = argparse.ArgumentParser(
        description=(
            "根据 javdb URL 为本地已有视频文件生成 movie.nfo 和图片，"
            "全部输出到该视频所在目录，不复制视频。"
        )
    )
    parser.add_argument(
        "--url",
        required=True,
        help="影片页面 URL（当前支持 javdb，例如：https://javdb.com/v/82ebmO）",
    )
    parser.add_argument(
        "--video",
        required=True,
        help="本地已有视频文件路径，例如：/path/to/movie.mp4",
    )
    parser.add_argument(
        "--rename-format",
        default=None,
        metavar="FMT",
        help=f"重命名格式，留空则不重命名。默认：{DEFAULT_RENAME_FORMAT}。占位符：id/year/date/actor/title/vr/resolution/idx",
    )
    parser.add_argument(
        "--download-concurrency",
        type=int,
        default=None,
        help="extrafanart 并发下载数（默认 4）",
    )
    parser.add_argument(
        "--http-timeout",
        type=int,
        default=None,
        help="单个 HTTP 请求超时秒数（默认 20）",
    )
    parser.add_argument(
        "--batch-timeout",
        type=int,
        default=None,
        help="extrafanart 批量下载总超时秒数（默认 120）",
    )

    args = parser.parse_args(argv)

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.is_file():
        raise SystemExit(f"视频文件不存在：{video_path}")

    settings = get_settings()
    metadata = scrape_movie(args.url, settings=settings)
    nfo_text = build_movie_nfo(metadata)

    result = save_assets_for_existing_video(
        metadata=metadata,
        nfo_text=nfo_text,
        video_path=video_path,
        settings=settings,
        max_extra_images=settings.max_extra_images,
        rename_format=args.rename_format or None,
        download_concurrency=args.download_concurrency
        if args.download_concurrency is not None
        else 4,
        http_timeout=args.http_timeout if args.http_timeout is not None else 20,
        batch_timeout=args.batch_timeout if args.batch_timeout is not None else 120,
    )

    print("刮削成功 ✅")
    print(f"影片目录: {result.movie_dir}")
    print(f"NFO 文件: {result.nfo_path}")
    if result.poster_path:
        print(f"封面: {result.poster_path}")
    if result.fanart_path:
        print(f"背景图: {result.fanart_path}")
    if result.extra_images:
        print(f"剧照: {len(result.extra_images)} 张，位于 extrafanart/ 目录下")


if __name__ == "__main__":
    main()
