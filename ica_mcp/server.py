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
  get_product           – slå upp produkt via streckkod (EAN)
  add_product_to_shopping_list – streckkod → lägg produktens namn på en lista
  offers_on_my_list     – vilka varor på listan är på extrapris
  add_recipes_to_shopping_list – flera recept → ihopslagna ingredienser på en lista
  plan_dinners          – slumpa veckans middagar → samlad inköpslista

Auth sköts av client.py (OAuth via ims.icagruppen.se, token cachas i en per-
användare state-katalog). Kräver svensk egress-IP (annars HTTP 451).

Kör:  ica-mcp serve   (eller: python -m ica_mcp)   — stdio, startas av MCP-klienten.
Logga in en gång först med `ica-mcp login`.
"""

from __future__ import annotations

import logging
import re
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


# ------------------------------------------------------------------ produkt
@mcp.tool()
def get_product(ean: str) -> dict:
    """Slå upp en produkt via streckkod (EAN/GTIN). Returnerar namn +
    artikelgrupp, eller found=False om koden inte finns."""
    p = client().get_product(str(ean).strip())
    if not p:
        return {"found": False, "ean": ean, "message": f"Ingen produkt för EAN {ean}."}
    return {"found": True, "ean": p.get("gtin"), "name": p.get("name"),
            "articleId": p.get("articleId"), "articleGroupId": p.get("articleGroupId")}


@mcp.tool()
def add_product_to_shopping_list(ean: str, list_name: str | None = None) -> str:
    """Slå upp en streckkod (EAN/GTIN) och lägg produktens namn på en lista.
    Utelämna list_name för primärlistan."""
    c = client()
    p = c.get_product(str(ean).strip())
    if not p:
        return f"Ingen produkt hittades för EAN {ean}."
    L = c.resolve_list(list_name)
    c.add_rows(L["offlineId"], [p["name"]])
    return f"La till '{p['name']}' på '{L.get('title')}'."


# --------------------------------------------------------- smarta flöden
@mcp.tool()
def offers_on_my_list(list_name: str | None = None,
                      store_name: str | None = None) -> dict:
    """Korsa din inköpslista mot en butiks aktuella erbjudanden — visar vilka
    ännu ej avbockade varor på listan som är på extrapris. Utelämna
    list_name/store_name för primärlistan / din primära butik."""
    c = client()
    L = c.resolve_list(list_name)
    fresh = c.get_list_raw(L["offlineId"])
    store = c.resolve_store(store_name)
    offers = c.get_store_offers(store["id"])
    on_sale = []
    for row in fresh.get("rows", []):
        if row.get("isStrikedOver"):
            continue
        item = (row.get("productName") or "").strip()
        words = [w for w in re.split(r"[^0-9a-zåäö]+", item.lower()) if len(w) >= 3]
        if not words:
            continue
        hits = [IcaClient.format_offer(o) for o in offers
                if any(w in (o.get("name") or "").lower() for w in words)]
        if hits:
            on_sale.append({"item": item,
                            "offers": [{"name": h["name"], "brand": h["brand"],
                                        "deal": h["deal"]} for h in hits]})
    return {"list": fresh.get("title"), "store": store.get("name"),
            "on_sale": on_sale,
            "summary": f"{len(on_sale)} vara/varor på listan har erbjudanden på {store.get('name')}"}


@mcp.tool()
def add_recipes_to_shopping_list(recipe_ids: list[int],
                                 list_name: str | None = None) -> str:
    """Lägg ingredienserna från FLERA recept på en lista, ihopslagna (samma
    vara + enhet summeras). Utelämna list_name för primärlistan."""
    c = client()
    recipes = []
    for rid in recipe_ids:
        try:
            recipes.append(c.get_recipe(rid))
        except IcaError:
            pass
    if not recipes:
        return "Kunde inte hämta något av recepten."
    items = IcaClient.aggregate_ingredients(recipes)
    L = c.resolve_list(list_name)
    c.add_rows(L["offlineId"], items)
    titles = ", ".join(r.get("title") or "?" for r in recipes)
    return (f"La till {len(items)} ihopslagna ingredienser från {len(recipes)} "
            f"recept ({titles}) på '{L.get('title')}'.")


@mcp.tool()
def plan_dinners(count: int = 5, list_name: str | None = None) -> dict:
    """Planera veckans middagar: hämtar `count` slumprecept (1–10), slår ihop
    deras ingredienser och lägger på en lista (skapar 'Veckans middagar' om
    list_name utelämnas). Returnerar menyn."""
    count = max(1, min(int(count), 10))
    c = client()
    recipes = c.get_random_recipes(count)
    if not recipes:
        return {"error": "Kunde inte hämta recept."}
    items = IcaClient.aggregate_ingredients(recipes)
    L = c.resolve_or_create_list(list_name or "Veckans middagar")
    c.add_rows(L["offlineId"], items)
    return {
        "list": L.get("title"),
        "dinners": [{"id": r.get("id"), "title": r.get("title"),
                     "cookingTime": r.get("cookingTime")} for r in recipes],
        "ingredients_added": len(items),
    }


def serve() -> None:
    """Starta MCP-servern (stdio). Anropas av `ica-mcp serve`."""
    mcp.run()


if __name__ == "__main__":
    serve()
