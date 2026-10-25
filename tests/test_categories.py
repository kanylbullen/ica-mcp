"""Varukategorier: namn → ICA:s id-par, rad → namn, och att add_rows och
add_items sätter dem."""

import pytest

from ica_mcp import server
from ica_mcp.client import (
    ARTICLE_GROUPS,
    IcaClient,
    IcaError,
    category_name,
    resolve_category,
)


def _ids(name):
    c = resolve_category(name)
    return c.group_id, c.extended_id


# ----------------------------------------------------------- resolve_category
@pytest.mark.parametrize("name, expected", [
    ("Mejeri", (10, 10)),
    ("mejeri", (10, 10)),
    ("  MEJERI ", (10, 10)),
    ("Ost", (6, 13)),
    ("Blommor", (11, 17)),
    ("Tidningar", (8, 23)),
])
def test_resolve_exact_name(name, expected):
    assert _ids(name) == expected


def test_resolve_returns_canonical_name():
    assert resolve_category("frukt").name == "Frukt & Grönt"


def test_resolve_treats_and_and_ampersand_alike():
    assert _ids("frukt och grönt") == (4, 4)
    assert _ids("Kläder & skor") == (11, 35)


def test_resolve_nfd_input():
    # "ö" som o + kombinerande trema.
    assert _ids("Frukt & Grönt") == (4, 4)


@pytest.mark.parametrize("name, expected", [
    ("godis", (9, 19)),
    ("frukt", (4, 4)),
    ("grönt", (4, 4)),     # början av ett senare ord
    ("skor", (11, 35)),
])
def test_resolve_unique_word_prefix(name, expected):
    assert _ids(name) == expected


@pytest.mark.parametrize("name", ["hushåll", "is", "mat"])
def test_resolve_does_not_match_inside_a_word(name):
    # hushåll ⊂ elhushåll, is ⊂ fisk, mat ⊂ färdigmat — inget av dem ska träffa.
    with pytest.raises(IcaError, match="Okänd kategori"):
        resolve_category(name)


def test_resolve_exact_beats_prefix():
    # "Städ" är både en egen kategori och början av "Städ & disk".
    assert _ids("städ") == (11, 27)


def test_resolve_ambiguous_prefix_raises():
    with pytest.raises(IcaError, match="Flera kategorier") as exc:
        resolve_category("kök")
    assert "Kök, hem & fritid" in str(exc.value) and "Köket" in str(exc.value)


def test_resolve_unknown_lists_valid_names():
    with pytest.raises(IcaError, match="Okänd kategori") as exc:
        resolve_category("rymdskepp")
    assert "Frukt & Grönt" in str(exc.value)


@pytest.mark.parametrize("name", ["", "   "])
def test_resolve_blank_is_unknown(name):
    with pytest.raises(IcaError, match="Okänd kategori"):
        resolve_category(name)


def test_every_parent_is_a_main_group():
    mains = {gid for gid, (_, parent) in ARTICLE_GROUPS.items() if gid == parent}
    assert mains == set(range(3, 13))
    assert all(parent in mains for _, parent in ARTICLE_GROUPS.values())


# ------------------------------------------------------------- category_name
def test_category_name_prefers_extended():
    assert category_name({"articleGroupId": 9, "articleGroupIdExtended": 18}) == "Dryck"


def test_category_name_falls_back_to_main():
    assert category_name({"articleGroupId": 12, "articleGroupIdExtended": None}) == "Ospecificerat"


@pytest.mark.parametrize("row", [{}, {"articleGroupId": None}, {"articleGroupId": 999}])
def test_category_name_none_when_missing_or_unknown(row):
    assert category_name(row) is None


# --------------------------------------------------------------- add_rows
def _capture_add_rows(items):
    client = IcaClient.__new__(IcaClient)
    sent = {}
    client._sync = lambda offline_id, payload: sent.update(payload) or {}
    client.add_rows("LIST", items)
    return sent["createdRows"]


def test_add_rows_sets_category_pair():
    (row,) = _capture_add_rows([{"name": "tulpaner", "category": "Blommor"}])
    assert (row["articleGroupId"], row["articleGroupIdExtended"]) == (11, 17)


@pytest.mark.parametrize("category", [None, "", "  "])
def test_add_rows_leaves_category_to_ica_when_unset(category):
    rows = _capture_add_rows(["mjölk", {"name": "grädde", "category": category}])
    assert all("articleGroupId" not in r and "articleGroupIdExtended" not in r for r in rows)


def test_add_rows_unknown_category_sends_nothing():
    client = IcaClient.__new__(IcaClient)
    client._sync = lambda *a: pytest.fail("ska inte synka när en kategori är okänd")
    with pytest.raises(IcaError):
        client.add_rows("LIST", [{"name": "a"}, {"name": "b", "category": "rymdskepp"}])


# ---------------------------------------------------------- server: add_items
class _FakeClient:
    def __init__(self):
        self.added = None

    def resolve_list(self, ref):
        return {"offlineId": "LIST", "title": "Handla"}

    def add_rows(self, offline_id, items):
        self.added = items


@pytest.fixture
def fake_client(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(server, "_client", fake)
    return fake


def test_add_items_without_category_leaves_it_to_ica(fake_client):
    msg = server.add_items(["mjölk", "bananer"])
    assert fake_client.added == [{"name": "mjölk", "category": None},
                                 {"name": "bananer", "category": None}]
    assert msg == "La till 2 vara/varor på 'Handla': mjölk, bananer"


def test_add_items_call_category_applies_to_all(fake_client):
    msg = server.add_items(["tulpaner", "vas"], category="blommor")
    assert [r["category"] for r in fake_client.added] == ["Blommor", "Blommor"]
    assert msg.endswith("tulpaner (Blommor), vas (Blommor)")


def test_add_items_per_item_category_overrides_call_category(fake_client):
    server.add_items(["mjölk",
                      server.Item(name="hundmat", category="djur"),
                      server.Item(name="tulpaner")],
                     category="Blommor")
    assert [(r["name"], r["category"]) for r in fake_client.added] == [
        ("mjölk", "Blommor"), ("hundmat", "Djur"), ("tulpaner", "Blommor")]


def test_add_items_blank_category_is_none(fake_client):
    server.add_items(["mjölk"], category="  ")
    assert fake_client.added == [{"name": "mjölk", "category": None}]


def test_add_items_unknown_category_adds_nothing(fake_client):
    with pytest.raises(IcaError):
        server.add_items(["mjölk", server.Item(name="x", category="rymdskepp")])
    assert fake_client.added is None


# ---------------------------------------------------------- server: _row_view
def test_row_view_includes_category():
    v = server._row_view({"productName": "ost", "articleGroupId": 6, "articleGroupIdExtended": 13})
    assert v == {"name": "ost", "checked": False, "category": "Ost"}


def test_row_view_omits_missing_category():
    assert "category" not in server._row_view({"productName": "x"})
