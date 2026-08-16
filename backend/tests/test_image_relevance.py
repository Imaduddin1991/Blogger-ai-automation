"""Phase 4C: deterministic image relevance scoring and query generation."""

from pipeline.images.query import generate_image_queries
from pipeline.images.relevance import MIN_RELEVANCE, compute_image_relevance


# --- Relevance: cat/cats and friends ------------------------------------------


def test_cats_matches_cat():
    assert compute_image_relevance("cats", "Cat on Windowsill", None) == 1.0


def test_dogs_matches_dog():
    assert compute_image_relevance("dogs", "Dog park guide", None) == 1.0


def test_stories_matches_story():
    assert compute_image_relevance("stories", "Short story collection", None) == 1.0


def test_plural_pair_via_ies():
    assert compute_image_relevance("puppies", "Puppy training basics", None) == 1.0


def test_unrelated_topic_scores_zero():
    assert compute_image_relevance("space rockets", "Cat on Windowsill", None) == 0.0


def test_relevant_title_with_different_word_form():
    assert compute_image_relevance("training", "Train your dog", None) == 1.0


def test_very_short_and_common_words_dropped():
    assert compute_image_relevance("a cat on a mat", "Cat mat", None) == 1.0
    assert compute_image_relevance("a an on at", "Cat mat", None) == 0.5  # only 1-2 char words: neutral


def test_empty_query_is_neutral():
    assert compute_image_relevance("", "Cat on Windowsill", None) == 0.5


def test_punctuation_is_normalized():
    assert compute_image_relevance("cats, dogs!", "Cats and Dogs", None) == 1.0


def test_no_fuzzy_prefix_overmatch():
    assert compute_image_relevance("cat", "Catering services", None) == 0.0


def test_relevance_is_bounded_and_deterministic():
    assert compute_image_relevance("cats", "Cat on Windowsill", None) == compute_image_relevance(
        "cats", "Cat on Windowsill", None
    )
    assert 0.0 <= compute_image_relevance("cats", "Cat food review", None) <= 1.0


def test_min_relevance_threshold_unchanged():
    assert MIN_RELEVANCE == 0.2


# --- Query generation ----------------------------------------------------------


def test_query_generation_is_deterministic():
    args = ("how to train cats", "Cat training guide", ("Feeding kittens", "Grooming tips"), ("Cat behavior",))
    assert generate_image_queries(*args) == generate_image_queries(*args)


def test_query_generation_bounded():
    queries = generate_image_queries(
        "solar panels",
        "Why solar works",
        ("How panels convert light", "Cost breakdown", "Maintenance tips", "Extra heading"),
        ("Solar energy basics",),
    )
    assert 1 <= len(queries) <= 3
    assert all(len(q.split()) <= 5 for q in queries)


def test_query_generation_keeps_topic_terms():
    queries = generate_image_queries("how to train cats")
    joined = " ".join(queries)
    assert "cats" in joined
    assert "train" in joined


def test_query_generation_strips_stopwords_from_keywords():
    queries = generate_image_queries("how to train cats", "Cat training guide")
    keyword_queries = queries[1:]
    assert all("how" not in q for q in keyword_queries)
    assert all("to" not in q for q in keyword_queries)


def test_query_generation_removes_duplicate_terms():
    queries = generate_image_queries("solar solar panels", "Solar power")
    assert all(len(q.split()) == len(set(q.split())) for q in queries)
    assert len(queries) == len(set(q.lower() for q in queries))


def test_query_generation_uses_headings():
    queries = generate_image_queries("", "", ("Feeding kittens", "Grooming tips"), ())
    joined = " ".join(queries)
    assert "feeding" in joined  # strongest keyword came from the headings


def test_query_generation_uses_research_terms():
    queries = generate_image_queries("", "", (), ("Feline nutrition",))
    joined = " ".join(queries)
    assert "feline" in joined  # strongest keyword came from the research titles


def test_query_generation_empty_inputs():
    assert generate_image_queries("") == []
    assert generate_image_queries("", "", (), ()) == []


def test_query_generation_falls_back_to_title():
    queries = generate_image_queries("", "Cat training guide")
    assert queries and "Cat training guide" in queries


def test_query_generation_no_llm():
    import asyncio

    queries = generate_image_queries("solar panels", "Why solar works", ("How panels work",), ())
    assert asyncio.iscoroutine(queries) is False  # synchronous, deterministic
    assert isinstance(queries, list)
