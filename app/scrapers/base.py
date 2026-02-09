from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from app.config import Settings
from app.schemas import MovieMetadata


class BaseScraper(ABC):
    """站点刮削器抽象基类。

    每个具体站点实现 `supports` 与 `scrape` 方法。
    """

    name: str = "base"

    @abstractmethod
    def supports(self, url: str) -> bool:  # pragma: no cover - 接口定义
        """当前 scraper 是否支持给定 URL。"""

    @abstractmethod
    def scrape(self, url: str, settings: Settings) -> MovieMetadata:  # pragma: no cover
        """从 URL 抓取并解析影片信息，返回统一的 MovieMetadata。"""


class ScraperFactory(Protocol):
    """用于 typing 的工厂协议，便于后续扩展。"""

    def __call__(self) -> BaseScraper:  # pragma: no cover - 类型辅助
        ...

