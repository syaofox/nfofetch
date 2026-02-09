from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring

from app.schemas import MovieMetadata


def build_movie_nfo(metadata: MovieMetadata) -> str:
    """根据影片元数据生成 Jellyfin/Kodi 兼容的 movie.nfo XML 字符串。"""

    movie_el = Element("movie")

    def set_text(parent: Element, tag: str, value: str | None) -> None:
        if value:
            el = SubElement(parent, tag)
            el.text = value

    set_text(movie_el, "title", metadata.title)
    set_text(movie_el, "originaltitle", metadata.original_title)
    set_text(movie_el, "sorttitle", metadata.number or metadata.title)
    set_text(movie_el, "plot", metadata.plot)

    if metadata.year:
        set_text(movie_el, "year", str(metadata.year))

    set_text(movie_el, "releasedate", metadata.releasedate)
    set_text(movie_el, "premiered", metadata.premiered)

    if metadata.runtime:
        set_text(movie_el, "runtime", str(metadata.runtime))

    # 用番号作为 <id>，便于 Jellyfin 识别
    set_text(movie_el, "id", metadata.number)

    set_text(movie_el, "studio", metadata.studio)
    set_text(movie_el, "label", metadata.label)
    set_text(movie_el, "series", metadata.series)

    # 评分
    if metadata.rating is not None:
        set_text(movie_el, "rating", f"{metadata.rating:.1f}")

    for tag in metadata.tags:
        set_text(movie_el, "tag", tag)

    for genre in metadata.genres:
        set_text(movie_el, "genre", genre)

    # 导演
    for director in metadata.directors:
        set_text(movie_el, "director", director)

    # 演员
    for actor in metadata.actors:
        actor_el = SubElement(movie_el, "actor")
        set_text(actor_el, "name", actor.name)
        if actor.role:
            set_text(actor_el, "role", actor.role)
        if actor.thumb:
            set_text(actor_el, "thumb", str(actor.thumb))

    # thumb 一般用于远程海报 URL，这里取第一张封面
    if metadata.posters:
        set_text(movie_el, "thumb", str(metadata.posters[0]))

    xml_bytes = tostring(movie_el, encoding="utf-8")
    return xml_bytes.decode("utf-8")

