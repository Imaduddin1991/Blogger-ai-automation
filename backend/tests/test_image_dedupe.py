"""Phase 4C: image deduplication and cross-article usage awareness."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import Article, Image
from pipeline.images.dedupe import canonical_image_url, dedupe_candidates, find_image_usage
from pipeline.images.providers.base import ImageResult


def _result(url: str, **overrides) -> ImageResult:
    result = ImageResult(
        provider="commons",
        image_url=url,
        page_url="https://commons.wikimedia.org/wiki/File:A.jpg",
        title="A cat",
        license="CC BY-SA 4.0",
        author="Jane Doe",
        attribution_required=True,
        mime="image/jpeg",
        relevance=0.8,
    )
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


# --- canonical_image_url -------------------------------------------------------


def test_canonical_url_lowercases_host_and_scheme():
    assert canonical_image_url("HTTPS://UPLOAD.WIKIMEDIA.ORG/a.jpg") == "https://upload.wikimedia.org/a.jpg"


def test_canonical_url_strips_trailing_slash_and_fragment():
    assert canonical_image_url("https://upload.wikimedia.org/a.jpg/") == "https://upload.wikimedia.org/a.jpg"
    assert canonical_image_url("https://upload.wikimedia.org/a.jpg#frag") == "https://upload.wikimedia.org/a.jpg"


def test_canonical_url_drops_default_port():
    assert canonical_image_url("https://upload.wikimedia.org:443/a.jpg") == "https://upload.wikimedia.org/a.jpg"


def test_canonical_url_sorts_query_params():
    assert canonical_image_url("https://x.example/a.jpg?b=2&a=1") == "https://x.example/a.jpg?a=1&b=2"


def test_canonical_url_preserves_distinct_paths():
    a = canonical_image_url("https://upload.wikimedia.org/a.jpg")
    b = canonical_image_url("https://upload.wikimedia.org/b.jpg")
    assert a != b


def test_canonical_url_empty():
    assert canonical_image_url("") == ""


# --- dedupe_candidates ----------------------------------------------------------


def test_exact_duplicate_collapsed():
    results = dedupe_candidates([_result("https://upload.wikimedia.org/a.jpg"), _result("https://upload.wikimedia.org/a.jpg")])
    assert len(results) == 1


def test_equivalent_url_variants_collapsed():
    results = dedupe_candidates(
        [
            _result("https://upload.wikimedia.org/a.jpg"),
            _result("https://UPLOAD.WIKIMEDIA.ORG/a.jpg/"),
            _result("https://upload.wikimedia.org:443/a.jpg#section"),
        ]
    )
    assert len(results) == 1


def test_best_relevance_wins_duplicate():
    results = dedupe_candidates(
        [
            _result("https://upload.wikimedia.org/a.jpg", relevance=0.3),
            _result("https://upload.wikimedia.org/a.jpg", relevance=0.9),
        ]
    )
    assert len(results) == 1
    assert results[0].relevance == 0.9


def test_distinct_images_remain_distinct():
    results = dedupe_candidates(
        [
            _result("https://upload.wikimedia.org/cat1.jpg", title="Cat on windowsill"),
            _result("https://upload.wikimedia.org/cat2.jpg", title="Cat on couch"),
        ]
    )
    assert len(results) == 2


def test_near_identical_title_collapsed_within_provider():
    results = dedupe_candidates(
        [
            _result("https://upload.wikimedia.org/cat1.jpg", title="Cat on Windowsill"),
            _result("https://upload.wikimedia.org/cat2.jpg", title="cat on  windowsill"),
        ]
    )
    assert len(results) == 1


def test_same_title_different_providers_stay_distinct():
    results = dedupe_candidates(
        [
            _result("https://upload.wikimedia.org/cat1.jpg", title="Cat", provider="commons"),
            _result("https://images.pexels.com/cat2.jpg", title="Cat", provider="pexels"),
        ]
    )
    assert len(results) == 2


def test_dedupe_across_providers_by_url():
    results = dedupe_candidates(
        [
            _result("https://upload.wikimedia.org/cat1.jpg", provider="commons"),
            _result("https://upload.wikimedia.org/cat1.jpg/", provider="openverse"),
        ]
    )
    assert len(results) == 1


# --- cross-article usage ---------------------------------------------------------


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_maker = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_maker()
    yield session
    session.close()


def _attach(db, article, url, status="selected"):
    image = Image(article_id=article.id, provider="commons", url=url, status=status)
    db.add(image)
    return image


def test_find_image_usage_reports_other_articles(db):
    first = Article(title="First", body="x")
    second = Article(title="Second", body="y")
    db.add_all([first, second])
    db.flush()
    _attach(db, first, "https://upload.wikimedia.org/shared.jpg")
    db.commit()

    usage = find_image_usage(db, "https://UPLOAD.WIKIMEDIA.ORG/shared.jpg/", exclude_article_id=second.id)
    assert len(usage) == 1
    assert usage[0]["article_id"] == first.id
    assert usage[0]["article_title"] == "First"
    assert usage[0]["status"] == "selected"


def test_find_image_usage_excludes_current_article(db):
    first = Article(title="First", body="x")
    db.add(first)
    db.flush()
    _attach(db, first, "https://upload.wikimedia.org/shared.jpg")
    db.commit()

    usage = find_image_usage(db, "https://upload.wikimedia.org/shared.jpg", exclude_article_id=first.id)
    assert usage == []


def test_find_image_usage_does_not_block_human_reuse(db):
    # The approved plan never hard-blocks reuse: humans may re-select an image
    # used elsewhere; the helper only reports it.
    first = Article(title="First", body="x")
    db.add(first)
    db.flush()
    _attach(db, first, "https://upload.wikimedia.org/shared.jpg")
    db.commit()
    assert find_image_usage(db, "https://upload.wikimedia.org/shared.jpg")  # informational
    assert find_image_usage(db, "https://upload.wikimedia.org/other.jpg") == []
