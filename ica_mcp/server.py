#!/usr/bin/env python3
"""
ICA MCP-server (stdio) — låter agenter läsa och redigera dina ICA-inköpslistor.

Verktyg:
  list_shopping_lists   – alla dina listor + hur många varor kvar/avbockade
  view_shopping_list    – innehållet i en lista
  add_items             – lägg till varor (fri text) på en lista
  check_off / uncheck   – bocka av / ångra en vara
  remove_item           – ta bort en vara helt
  create_shopping_list  – skapa ny lista
  delete_shopping_list  – radera en lista
  clear_checked         – ta bort alla avbockade varor
  list_saved_recipes    – dina favoritrecept
  get_recipe            – ett recept med ingredienser + steg
  random_recipes        – slumprecept för inspiration
  add_recipe_to_shopping_list – lägg receptets ingredienser på en lista
  list_stores           – dina favoritbutiker
  get_offers            – aktuella erbjudanden för en butik
  get_bonus             – din ICA-bonus/Stammis

Auth sköts av client.py (OAuth via ims.icagruppen.se, token cachas i en per-
användare state-katalog). Kräver svensk egress-IP (annars HTTP 451).

Kör:  ica-mcp serve   (eller: python -m ica_mcp)   — stdio, startas av MCP-klienten.
Logga in en gång först med `ica-mcp login`.
"""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from .client import IcaClient, IcaError

# Logga till stderr (stdout är reserverat för MCP-protokollet!)
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(levelname)s %(name)s: %(message)s")
_LOG = logging.getLogger("ica_mcp")

mcp = FastMCP("ICA")
_client: IcaClient | None = None


def client() -> IcaClient:
    global _client
    if _client is None:
        _client = IcaClient()
    return _client


# ------------------------------------------------------------------ helpers
def _row_view(row: dict) -> dict:
    v = {"name": row.get("productName"), "checked": bool(row.get("isStrikedOver"))}
    if row.get("quantity") is not None:
        v["quantity"] = row["quantity"]
    if row.get("unit"):
        v["unit"] = row["unit"]
    return v


def _resolve_rows(list_obj: dict, item: str, unstruck_only: bool = False) -> list[dict]:
    """Returnera rader för EN vara. Fel om flera olika varor matchar."""
    matches = IcaClient.match_rows(list_obj, item, unstruck_only=unstruck_only)
    if not matches:
        avail = sorted({r.get("productName", "") for r in list_obj.get("rows", [])})
        raise IcaError(f"Ingen vara matchar {item!r} på '{list_obj.get('title')}'. "
                       f"Varor: {avail}")
    names = {r.get("productName", "").lower() for r in matches}
    if len(names) > 1:
        raise IcaError(f"Flera olika varor matchar {item!r}: "
                       f"{sorted({r.get('productName') for r in matches})}. Var mer specifik.")
    return matches


# -------------------------------------------------------------------- tools
@mcp.tool()
def list_shopping_lists() -> list[dict]:
    """Lista alla dina ICA-inköpslistor med antal varor kvar och avbockade.
    Den första listan är din primära ('Handla') och används som standard när
    inget listnamn anges i andra verktyg."""
    out = []
    for L in client().get_lists():
        rows = L.get("rows", [])
        remaining = sum(1 for r in rows if not r.get("isStrikedOver"))
        out.append({
            "name": L.get("title"),
            "remaining": remaining,
            "checked": len(rows) - remaining,
            "total": len(rows),
        })
    return out


@mcp.tool()
def view_shopping_list(list_name: str | None = None) -> dict:
    """Visa innehållet i en inköpslista. list_name matchas mot listans titel
    (utelämna för den primära listan). Returnerar varor uppdelat i kvar/avbockade."""
    L = client().resolve_list(list_name)
    fresh = client().get_list_raw(L["offlineId"])
    rows = fresh.get("rows", [])
    remaining = [_row_view(r) for r in rows if not r.get("isStrikedOver")]
    checked = [_row_view(r) for r in rows if r.get("isStrikedOver")]
    return {"list": fresh.get("title"), "remaining": remaining, "checked": checked,
            "summary": f"{len(remaining)} kvar, {len(checked)} avbockade"}


@mcp.tool()
def add_items(items: list[str], list_name: str | None = None) -> str:
    """Lägg till en eller flera varor (fri text, t.ex. 'mjölk', '2 kg potatis')
    på en inköpslista. Utelämna list_name för den primära listan."""
    if not items:
        return "Inga varor angivna."
    L = client().resolve_list(list_name)
    client().add_rows(L["offlineId"], list(items))
    return f"La till {len(items)} vara/varor på '{L.get('title')}': {', '.join(items)}"


@mcp.tool()
def check_off(item: str, list_name: str | None = None) -> str:
    """Bocka av en vara (markera som köpt/klar) på en lista."""
    c = client()
    L = c.resolve_list(list_name)
    fresh = c.get_list_raw(L["offlineId"])
    rows = _resolve_rows(fresh, item, unstruck_only=True)
    for r in rows:
        r["isStrikedOver"] = True
    c.change_rows(L["offlineId"], rows)
    return f"Bockade av '{rows[0].get('productName')}' på '{fresh.get('title')}'."


@mcp.tool()
def uncheck(item: str, list_name: str | None = None) -> str:
    """Ångra avbockning av en vara (markera som ej köpt igen)."""
    c = client()
    L = c.resolve_list(list_name)
    fresh = c.get_list_raw(L["offlineId"])
    rows = _resolve_rows(fresh, item)
    for r in rows:
        r["isStrikedOver"] = False
    c.change_rows(L["offlineId"], rows)
    return f"Ångrade avbockning av '{rows[0].get('productName')}' på '{fresh.get('title')}'."


@mcp.tool()
def remove_item(item: str, list_name: str | None = None) -> str:
    """Ta bort en vara helt från en lista (inte samma som att bocka av)."""
    c = client()
    L = c.resolve_list(list_name)
    fresh = c.get_list_raw(L["offlineId"])
    rows = _resolve_rows(fresh, item)
    c.delete_rows(L["offlineId"], [r["offlineId"] for r in rows])
    return f"Tog bort '{rows[0].get('productName')}' från '{fresh.get('title')}'."


@mcp.tool()
def clear_checked(list_name: str | None = None) -> str:
    """Ta bort alla avbockade varor från en lista (rensa upp efter handling)."""
    c = client()
    L = c.resolve_list(list_name)
    fresh = c.get_list_raw(L["offlineId"])
    struck = [r["offlineId"] for r in fresh.get("rows", []) if r.get("isStrikedOver")]
    if not struck:
        return f"Inga avbockade varor att rensa på '{fresh.get('title')}'."
    c.delete_rows(L["offlineId"], struck)
    return f"Rensade {len(struck)} avbockade varor från '{fresh.get('title')}'."


@mcp.tool()
def create_shopping_list(title: str) -> str:
    """Skapa en ny inköpslista med angiven titel."""
    L = client().create_list(title)
    return f"Skapade listan '{L.get('title')}'."


@mcp.tool()
def delete_shopping_list(list_name: str) -> str:
    """Radera en hel inköpslista (kräver att du anger listnamnet explicit)."""
    L = client().resolve_list(list_name)
    title = L.get("title")
    client().delete_list(L["offlineId"])
    return f"Raderade listan '{title}'."


# ------------------------------------------------------------------ recept
@mcp.tool()
def list_saved_recipes(limit: int = 12) -> dict:
    """Lista dina favoritmarkerade recept (senast tillagda först). Hämtar
    detaljer per recept, så håll limit lågt (standard 12)."""
    c = client()
    refs = sorted(c.get_saved_recipe_refs(),
                  key=lambda r: r.get("createdDate", ""), reverse=True)
    picked = refs[:max(1, int(limit))]
    recipes = []
    for ref in picked:
        try:
            recipes.append(IcaClient.recipe_summary(c.get_recipe(ref["recipeId"])))
        except IcaError:
            recipes.append({"id": ref.get("recipeId"), "title": None})
    return {"total_saved": len(refs), "showing": len(recipes), "recipes": recipes}


@mcp.tool()
def get_recipe(recipe_id: int) -> dict:
    """Hämta ett recept: titel, tid, portioner, ingredienser (fri text) och
    tillagningssteg."""
    r = client().get_recipe(recipe_id)
    s = IcaClient.recipe_summary(r)
    s["ingredients"] = IcaClient.recipe_ingredient_texts(r)
    s["steps"] = (r.get("details") or {}).get("cookingSteps") or []
    return s


@mcp.tool()
def random_recipes(count: int = 3) -> list[dict]:
    """Hämta slumpmässiga recept för inspiration (count 1–10)."""
    count = max(1, min(int(count), 10))
    return [IcaClient.recipe_summary(r) for r in client().get_random_recipes(count)]


@mcp.tool()
def add_recipe_to_shopping_list(recipe_id: int, list_name: str | None = None) -> str:
    """Lägg alla ingredienser från ett recept som varor på en inköpslista
    (fri text, t.ex. '8 dl mjölk'). Utelämna list_name för primärlistan."""
    c = client()
    recipe = c.get_recipe(recipe_id)
    items = IcaClient.recipe_ingredient_texts(recipe)
    if not items:
        return f"Receptet '{recipe.get('title')}' saknar ingredienser."
    L = c.resolve_list(list_name)
    c.add_rows(L["offlineId"], items)
    return (f"La till {len(items)} ingredienser från '{recipe.get('title')}' "
            f"på '{L.get('title')}'.")


# ------------------------------------------------------ erbjudanden / butiker
@mcp.tool()
def list_stores() -> list[dict]:
    """Lista dina favoritbutiker (id, namn, ort). Den första är standardbutik
    för erbjudanden."""
    return client().get_favorite_stores()


@mcp.tool()
def get_offers(store_name: str | None = None, query: str | None = None,
               limit: int = 40) -> dict:
    """Hämta aktuella erbjudanden för en butik. store_name matchas mot dina
    favoritbutiker (utelämna för din primära butik). query filtrerar på
    varunamn/märke/kategori (t.ex. 'kaffe')."""
    c = client()
    store = c.resolve_store(store_name)
    offers = [IcaClient.format_offer(o) for o in c.get_store_offers(store["id"])]
    if query:
        q = str(query).lower()
        # matcha varunamn/märke — INTE kategori (ordet 'Skafferivaror' innehåller
        # t.ex. delsträngen 'kaffe' och skulle ge falska träffar)
        offers = [o for o in offers if q in " ".join(
            str(o.get(k) or "") for k in ("name", "brand")).lower()]
    return {"store": store.get("name"), "count": len(offers),
            "offers": offers[:max(1, int(limit))]}


@mcp.tool()
def get_bonus() -> dict:
    """Visa din ICA-bonus/Stammis: kupongvärde, aktiva kuponger och rabatt hittills."""
    b = client().get_bonus()
    ab = b.get("accountBalance") or {}
    ds = b.get("discountSummary") or {}
    return {
        "totalVoucherValue": ab.get("totalVoucherValue"),
        "nextVoucherValue": ab.get("nextVoucherValue"),
        "remainingDays": ab.get("remainingDays"),
        "activeVouchers": len((b.get("vouchers") or {}).get("active") or []),
        "totalDiscount": ds.get("totalDiscount"),
        "numberOfPurchases": ds.get("numberOfPurchases"),
    }


def serve() -> None:
    """Starta MCP-servern (stdio). Anropas av `ica-mcp serve`."""
    mcp.run()


if __name__ == "__main__":
    serve()
