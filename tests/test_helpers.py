"""Enhetstester för de rena (nätfria) hjälpfunktionerna i ica_mcp.client.

Dessa rör aldrig ICA:s API — de testar aggregering, formatering, matchning och
parsning. Live-API:t kan inte testas i CI (kräver svensk IP + inloggning)."""

import base64
import hashlib

import pytest

from ica_mcp.client import (
    IcaAuthError,
    IcaClient,
    _ensure_parent_dir,
    resolve_state_file,
)


def _recipe(*ingredients):
    return {"ingredientGroups": [{"ingredients": list(ingredients)}]}


# ----------------------------------------------------------- aggregate_ingredients
def test_aggregate_sums_same_name_and_unit():
    r1 = _recipe({"ingredient": "mjölk", "quantity": 8, "unit": "dl", "text": "8 dl mjölk"})
    r2 = _recipe({"ingredient": "mjölk", "quantity": 2, "unit": "dl", "text": "2 dl mjölk"})
    assert IcaClient.aggregate_ingredients([r1, r2]) == ["10 dl mjölk"]


def test_aggregate_sums_unitless_count():
    r1 = _recipe({"ingredient": "ägg", "quantity": 4, "text": "4 ägg"})
    r2 = _recipe({"ingredient": "ägg", "quantity": 2, "text": "2 ägg"})
    assert IcaClient.aggregate_ingredients([r1, r2]) == ["6 ägg"]


def test_aggregate_keeps_distinct_lines_on_unit_mismatch():
    r1 = _recipe({"ingredient": "smör", "quantity": 50, "unit": "g", "text": "50 g smör"})
    r2 = _recipe({"ingredient": "smör", "quantity": 1, "unit": "msk", "text": "1 msk smör"})
    assert IcaClient.aggregate_ingredients([r1, r2]) == ["50 g smör", "1 msk smör"]


def test_aggregate_empty():
    assert IcaClient.aggregate_ingredients([]) == []


# ----------------------------------------------------------- recipe helpers
def test_recipe_ingredient_texts_prefers_text():
    r = _recipe(
        {"text": "8 dl mjölk", "ingredient": "mjölk"},
        {"ingredient": "salt"},  # ingen text -> faller tillbaka på ingredient
    )
    assert IcaClient.recipe_ingredient_texts(r) == ["8 dl mjölk", "salt"]


def test_recipe_summary_maps_nested_portions():
    r = {"id": 1, "title": "Soppa", "cookingTime": "Under 30 minuter",
         "averageRating": 4.5, "details": {"portions": 4}}
    s = IcaClient.recipe_summary(r)
    assert s["id"] == 1 and s["title"] == "Soppa" and s["portions"] == 4 and s["rating"] == 4.5


# ----------------------------------------------------------- format_offer
def test_format_offer_builds_multi_part_deal():
    o = {"name": "Kaffe", "brand": "ICA", "isPersonal": True,
         "requiresLoyaltyCard": False, "category": {"articleGroupName": "Dryck"},
         "parsedMechanics": {"value1": "2 för", "value2": "115", "unitSign": ":-"}}
    f = IcaClient.format_offer(o)
    assert f["deal"] == "2 för 115:-"
    assert f["name"] == "Kaffe" and f["category"] == "Dryck" and f["personal"] is True


def test_format_offer_simple_price_and_missing_mechanics():
    assert IcaClient.format_offer(
        {"name": "X", "parsedMechanics": {"value1": "18", "unitSign": ":-"}}
    )["deal"] == "18:-"
    assert IcaClient.format_offer({"name": "Y"})["deal"] is None


# ----------------------------------------------------------- match_rows
def _list():
    return {"rows": [
        {"productName": "mjölk", "offlineId": "A", "isStrikedOver": False},
        {"productName": "lättmjölk", "offlineId": "B", "isStrikedOver": True},
        {"productName": "ägg", "offlineId": "C", "isStrikedOver": False},
    ]}


def test_match_rows_exact_beats_substring():
    m = IcaClient.match_rows(_list(), "mjölk")
    assert [r["offlineId"] for r in m] == ["A"]  # inte lättmjölk


def test_match_rows_substring_and_unstruck_filter():
    assert {r["offlineId"] for r in IcaClient.match_rows(_list(), "jölk")} == {"A", "B"}
    assert [r["offlineId"] for r in IcaClient.match_rows(_list(), "jölk", unstruck_only=True)] == ["A"]


def test_match_rows_by_offline_id():
    assert [r["offlineId"] for r in IcaClient.match_rows(_list(), "C")] == ["C"]


# ----------------------------------------------------------- _qs / _hidden
def test_qs_extracts_from_query_and_custom_scheme():
    assert IcaClient._qs("https://x/y?state=abc&code=def", "state") == "abc"
    assert IcaClient._qs("icacurity://app?code=xyz&state=q", "code") == "xyz"


def test_qs_raises_when_absent():
    with pytest.raises(IcaAuthError):
        IcaClient._qs("https://x/y", "state")


def test_hidden_extracts_both_attribute_orders():
    assert IcaClient._hidden('<input type="hidden" name="token" value="TT"/>', "token") == "TT"
    assert IcaClient._hidden('<input value="SS" name="state">', "state") == "SS"


def test_hidden_raises_when_absent():
    with pytest.raises(IcaAuthError):
        IcaClient._hidden("<form></form>", "token")


# ----------------------------------------------------------- _pkce
def test_pkce_challenge_is_s256_of_verifier():
    challenge, verifier = IcaClient._pkce()
    assert verifier.isalnum() and "=" not in challenge
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected


# ----------------------------------------------------------- state-file helpers
def test_resolve_state_file_honours_override(monkeypatch, tmp_path):
    target = tmp_path / "sub" / "auth.json"
    monkeypatch.setenv("ICA_STATE_FILE", str(target))
    assert resolve_state_file() == str(target)


def test_ensure_parent_dir_bare_filename_is_noop():
    _ensure_parent_dir("bare.json")  # får inte kasta (dirname == "")


def test_ensure_parent_dir_creates_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "f.json"
    _ensure_parent_dir(str(p))
    assert (tmp_path / "a" / "b").is_dir()
