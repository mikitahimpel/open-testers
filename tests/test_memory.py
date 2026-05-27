import pytest

from open_testers.memory import MemoryStore, VALID_CATEGORIES, VALID_IMPORTANCES


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "mem.json")


def test_empty_store(store):
    assert store.list() == []
    assert store.render_text() == ""
    assert store.to_llm_context() == []


def test_add_and_list(store):
    m = store.add("site_structure", "Login route", "Login is at /login", "high")
    assert m.id
    entries = store.list()
    assert len(entries) == 1
    assert entries[0].title == "Login route"
    assert entries[0].importance == "high"


def test_list_sorted_high_first(store):
    store.add("test_insights", "low one", "x", "low")
    store.add("site_structure", "high one", "x", "high")
    store.add("user_preferences", "medium one", "x", "medium")
    titles = [m.title for m in store.list()]
    assert titles == ["high one", "medium one", "low one"]


@pytest.mark.parametrize("category", VALID_CATEGORIES)
def test_all_valid_categories_accepted(store, category):
    store.add(category, "t", "c", "medium")


@pytest.mark.parametrize("importance", VALID_IMPORTANCES)
def test_all_valid_importances_accepted(store, importance):
    store.add("site_structure", "t", "c", importance)


def test_invalid_category_rejected(store):
    with pytest.raises(ValueError):
        store.add("bogus_category", "t", "c", "high")


def test_invalid_importance_rejected(store):
    with pytest.raises(ValueError):
        store.add("site_structure", "t", "c", "urgent")


def test_empty_title_rejected(store):
    with pytest.raises(ValueError):
        store.add("site_structure", "", "c", "high")


def test_empty_content_rejected(store):
    with pytest.raises(ValueError):
        store.add("site_structure", "t", "", "high")


def test_remove(store):
    m = store.add("site_structure", "x", "y", "high")
    assert store.remove(m.id) is True
    assert store.remove("nonexistent") is False
    assert store.list() == []


def test_render_text_groups_by_category(store):
    store.add("site_structure", "Login route", "/login", "high")
    store.add("test_insights", "Slow search", "debounces", "medium")
    text = store.render_text()
    assert "## Project memory" in text
    assert "### site_structure" in text
    assert "### test_insights" in text
    assert "[high]" in text
    assert "[medium]" in text


def test_to_llm_context_shape(store):
    store.add("site_structure", "Login route", "/login", "high")
    ctx = store.to_llm_context()
    assert len(ctx) == 1
    assert set(ctx[0].keys()) == {"category", "title", "content", "importance"}
