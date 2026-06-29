from __future__ import annotations

import pytest
from app.schemas import Actor, MovieMetadata


@pytest.fixture
def sample_movie_metadata() -> MovieMetadata:
    return MovieMetadata(
        title="ABP-123 我的女友",
        original_title="ABP-123 俺の彼女",
        number="ABP-123",
        plot="这是一个测试剧情。",
        year=2024,
        premiered="2024-03-15",
        releasedate="2024-03-15",
        runtime=120,
        genres=["爱情", "喜剧"],
        tags=["HD"],
        actors=[
            Actor(name="田中丽奈", role="主演", thumb=None),
            Actor(name="佐藤健", role="配角", thumb=None),
        ],
        studio="Prestige",
        label="Premium",
        series="Premium Beautiful",
        directors=["山田太郎"],
        rating=7.5,
        posters=[
            "https://example.com/poster1.jpg",
            "https://example.com/poster2.jpg",
        ],
        art=[
            "https://example.com/art1.jpg",
            "https://example.com/art2.jpg",
        ],
        source_url="https://javdb.com/v/abcdef",
    )


@pytest.fixture
def minimal_metadata() -> MovieMetadata:
    return MovieMetadata(
        title="Unknown Title",
    )
