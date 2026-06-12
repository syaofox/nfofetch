from __future__ import annotations

import pytest

from app.scrapers.base import BaseScraper


def test_abstract_class_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        BaseScraper()  # type: ignore[abstract]


class TestConcreteScraper:
    def test_subclass_must_implement_abstract_methods(self) -> None:
        class IncompleteScraper(BaseScraper):
            pass

        with pytest.raises(TypeError):
            IncompleteScraper()  # type: ignore[abstract]
