from __future__ import annotations

from datetime import datetime, timezone

from xml.etree.ElementTree import Element, SubElement, indent, tostring

from app.schemas import MovieMetadata


def build_movie_nfo(metadata: MovieMetadata) -> str:
    """根据影片元数据生成 Jellyfin/Emby 兼容的 movie.nfo XML 字符串。"""

    movie_el = Element("movie")

    def set_text(parent: Element, tag: str, value: str | None) -> None:
        if value:
            el = SubElement(parent, tag)
            el.text = value

    # Emby 通用字段
    set_text(movie_el, "title", metadata.title)
    set_text(movie_el, "originaltitle", metadata.original_title or metadata.title)
    set_text(movie_el, "sorttitle", metadata.number or metadata.title)
    set_text(movie_el, "plot", metadata.plot)
    set_text(movie_el, "outline", metadata.plot)

    if metadata.year:
        set_text(movie_el, "year", str(metadata.year))

    set_text(movie_el, "releasedate", metadata.releasedate)
    set_text(movie_el, "premiered", metadata.premiered)

    if metadata.runtime:
        set_text(movie_el, "runtime", str(metadata.runtime))

    # <id> 保留向后兼容
    set_text(movie_el, "id", metadata.number)
    # <uniqueid> 为 Kodi v18+ / Emby 标准识别码
    if metadata.number:
        uid_el = SubElement(movie_el, "uniqueid")
        uid_el.set("type", "nfofetch")
        uid_el.set("default", "true")
        uid_el.text = metadata.number

    set_text(movie_el, "studio", metadata.studio)
    set_text(movie_el, "label", metadata.label)

    # <series> 非标准 Kodi/Emby 元素，改用 <set><name>
    if metadata.series:
        set_el = SubElement(movie_el, "set")
        set_text(set_el, "name", metadata.series)

    # 评分（Emby 使用 criticrating，同时保留 rating 向后兼容）
    if metadata.rating is not None:
        set_text(movie_el, "rating", f"{metadata.rating:.1f}")
        set_text(movie_el, "criticrating", f"{metadata.rating:.1f}")

    for tag in metadata.tags:
        set_text(movie_el, "tag", tag)

    for genre in metadata.genres:
        set_text(movie_el, "genre", genre)

    # 导演
    for director in metadata.directors:
        set_text(movie_el, "director", director)

    # Emby 通用字段
    set_text(movie_el, "mpaa", "XXX")
    set_text(movie_el, "country", "Japan")

    # lockdata + dateadded（Emby 期望）
    set_text(movie_el, "lockdata", "false")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    set_text(movie_el, "dateadded", now)

    # 演员
    for actor in metadata.actors:
        actor_el = SubElement(movie_el, "actor")
        set_text(actor_el, "name", actor.name)
        if actor.role:
            set_text(actor_el, "role", actor.role)
        set_text(actor_el, "type", "Actor")
        if actor.thumb:
            set_text(actor_el, "thumb", str(actor.thumb))

    # thumb 一般用于远程海报 URL，这里取第一张封面
    if metadata.posters:
        set_text(movie_el, "thumb", str(metadata.posters[0]))

    indent(movie_el)
    xml_bytes = tostring(movie_el, encoding="utf-8")
    return xml_bytes.decode("utf-8")
