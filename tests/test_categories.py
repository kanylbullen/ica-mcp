"""Varukategorier: namn → ICA:s id-par, rad → namn, och att add_rows sätter dem."""

import pytest

from ica_mcp.client import (
    ARTICLE_GROUPS,
    IcaClient,
    IcaError,
    category_name,
    resolve_category,
)


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
    assert resolve_category(name) == expected


def test_resolve_treats_and_and_ampersand_alike():
    assert resolve_category("frukt och grönt") == (4, 4)
    assert resolve_category("Kläder & skor") == (11, 35)


def test_resolve_unique_partial():
    assert resolve_category("godis") == (9, 19)
    assert resolve_category("frukt") == (4, 4)


def test_resolve_exact_beats_partial():
    # "Städ" är både en egen kategori och ett delord i "Städ & disk".
    assert resolve_category("städ") == (11, 27)


def test_resolve_ambiguous_partial_raises():
    with pytest.raises(IcaError, match="Flera kategorier"):
        resolve_category("kök")  # Kök, hem & fritid / Köket


def test_resolve_unknown_lists_valid_names():
    with pytest.raises(IcaError, match="Okänd kategori") as exc:
        resolve_category("rymdskepp")
    assert "Frukt & Grönt" in str(exc.value)


def test_resolve_empty_is_unknown():
    with pytest.raises(IcaError, match="Okänd kategori"):
        resolve_category("")


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


def test_add_rows_leaves_category_to_ica_when_unset():
    rows = _capture_add_rows(["mjölk", {"name": "grädde", "category": None}])
    assert all("articleGroupId" not in r and "articleGroupIdExtended" not in r for r in rows)


def test_add_rows_unknown_category_sends_nothing():
    client = IcaClient.__new__(IcaClient)
    client._sync = lambda *a: pytest.fail("ska inte synka när en kategori är okänd")
    with pytest.raises(IcaError):
        client.add_rows("LIST", [{"name": "a"}, {"name": "b", "category": "rymdskepp"}])
