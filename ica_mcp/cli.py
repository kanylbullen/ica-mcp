"""ica-mcp CLI — ett kommando för hela livscykeln.

    ica-mcp serve      starta MCP-servern (stdio) — det MCP-klienten kör
    ica-mcp login      logga in en gång (personnummer + lösenord)
    ica-mcp status      visa var sessionen cachas och om den är giltig
    ica-mcp register   registrera servern i Claude Code (--scope user)

`login` måste vara ett separat kommando eftersom lösenordsprompten (getpass)
inte kan köras över stdio-transporten som servern använder. Den delar dock
numera EN kodväg med servern (ica_mcp.client), inte en egen dubblett.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys


# --------------------------------------------------------------------------- helpers
def _enable_utf8_console() -> None:
    """Låt oss skriva ut ✅/✖/→ även i en cp1252-konsol (Windows). Rör INTE
    serve-vägen — där är stdout MCP-protokollets kanal."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # redan utf-8, eller ej en TextIOWrapper
            pass


def _diagnose(exc: Exception) -> None:
    """Skriv ut ett begripligt, åtgärdbart felmeddelande på stderr."""
    import requests

    msg = str(exc)
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        print(f"\n✖ HTTP {code} mot {exc.response.url}", file=sys.stderr)
        if code == 451:
            print("  → 451 = geo-block. Du kör inte från en svensk IP. Kör hemma / "
                  "på homelab, inte på en utländsk VPS/VPN.", file=sys.stderr)
        elif code in (401, 403):
            print("  → Auth nekad. Kolla personnummer/lösenord, eller bot-block "
                  "(F5/Akamai).", file=sys.stderr)
        return
    if isinstance(exc, requests.RequestException):
        print(f"\n✖ Nätverksfel: {msg}", file=sys.stderr)
        return
    # IcaError / IcaAuthError bär redan ett läsbart meddelande (t.ex. 451-texten)
    print(f"\n✖ {msg}", file=sys.stderr)


def _ica_mcp_launch_argv() -> list[str]:
    """Robust sätt att starta servern oavsett PATH: samma Python som kör oss,
    med `-m ica_mcp serve`. Om ett fristående `ica-mcp`-skript finns på PATH
    föredras det (snyggare i konfigen)."""
    exe = shutil.which("ica-mcp")
    if exe and os.path.abspath(exe) != os.path.abspath(sys.argv[0] or ""):
        return [exe, "serve"]
    return [sys.executable, "-m", "ica_mcp", "serve"]


# --------------------------------------------------------------------------- commands
def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve
    serve()
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    import requests

    from .client import IcaAuthError, IcaClient, IcaError, resolve_state_file

    # --check: bara sondera en befintlig session, prompta aldrig.
    if args.check:
        try:
            lists = IcaClient().get_lists()
        except (IcaError, requests.RequestException) as e:
            print("Ingen giltig session — kör `ica-mcp login`.", file=sys.stderr)
            if args.verbose:
                _diagnose(e)
            return 1
        print(f"✅ Giltig session ({len(lists)} lista/listor).")
        return 0

    # Utan --fresh: hoppa över inloggning om cachen redan funkar (idempotent).
    if not args.fresh:
        try:
            probe = IcaClient()
            if probe.token_status()["access_valid"] or probe.token_status()["has_refresh"]:
                lists = probe.get_lists()
                who = probe.whoami()
                print(f"✅ Redan inloggad{(' som ' + who) if who else ''} "
                      f"({len(lists)} lista/listor). Använd --fresh för att logga in på nytt.")
                return 0
        except (IcaError, requests.RequestException):
            pass  # cachen dög inte — gå vidare till interaktiv inloggning

    username = os.environ.get("ICA_USER") or input("Personnummer (ÅÅÅÅMMDDXXXX): ").strip()
    password = os.environ.get("ICA_PASS") or getpass.getpass("Lösenord: ")
    if not username or not password:
        print("Saknar personnummer eller lösenord.", file=sys.stderr)
        return 2

    client = IcaClient(username=username, password=password)
    try:
        client.authenticate(force=True)
        lists = client.get_lists()
    except (IcaError, IcaAuthError, requests.RequestException) as e:
        _diagnose(e)
        return 1

    who = client.whoami()
    print(f"\n✅ Inloggad{(' som ' + who) if who else ''}.")
    print(f"   Session cachad i: {resolve_state_file()}")
    titles = ", ".join(L.get("title", "") for L in lists)
    print(f"   {len(lists)} lista/listor: {titles}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .client import IcaClient

    st = IcaClient().token_status()
    print(f"State-fil: {st['state_file']}")
    if not st["exists"]:
        print("Status:    ingen cache ännu — kör `ica-mcp login`.")
        return 1
    print(f"Access-token giltigt (lokalt): {'ja' if st['access_valid'] else 'nej'}")
    print(f"Refresh-token finns:           {'ja' if st['has_refresh'] else 'nej'}")
    print(f"Access-token utgår:            {st['expiry'] or '?'}")
    ok = st["access_valid"] or st["has_refresh"]
    if not ok:
        print("→ Sessionen kan inte förnyas — kör `ica-mcp login`.")
    return 0 if ok else 1


def cmd_register(args: argparse.Namespace) -> int:
    argv = _ica_mcp_launch_argv()
    claude = shutil.which("claude")
    mcp_json = {"mcpServers": {"ica": {"command": argv[0], "args": argv[1:]}}}

    if not claude:
        print("Hittade inte `claude`-CLI:t på PATH.")
        print("Lägg till servern manuellt i din MCP-klients config (mcp.json):\n")
        print(json.dumps(mcp_json, indent=2, ensure_ascii=False))
        return 1

    # Ta bort ev. gammal user-scope-post först (idempotent), ignorera fel.
    subprocess.run([claude, "mcp", "remove", "ica", "-s", "user"],
                   capture_output=True, text=True)
    r = subprocess.run([claude, "mcp", "add", "ica", "--scope", "user", "--", *argv],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"✖ `claude mcp add` misslyckades:\n{r.stderr or r.stdout}", file=sys.stderr)
        print("\nManuell config (mcp.json):\n")
        print(json.dumps(mcp_json, indent=2, ensure_ascii=False))
        return 1
    print("✅ Registrerade 'ica' i Claude Code (scope: user).")
    print(f"   Kommando: {' '.join(argv)}")
    print("   Ladda om / starta om Claude Code så dyker verktygen upp.")
    return 0


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ica-mcp",
        description="MCP-server för ICA:s inköpslistor. Kör `ica-mcp login` en gång, "
                    "sedan `ica-mcp register`.",
    )
    sub = ap.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="starta MCP-servern (stdio)")
    p_serve.set_defaults(func=cmd_serve)

    p_login = sub.add_parser("login", help="logga in (personnummer + lösenord)")
    p_login.add_argument("--fresh", action="store_true",
                         help="ignorera cache, tvinga ny inloggning")
    p_login.add_argument("--check", action="store_true",
                         help="sondera befintlig session utan att prompta (exit 0 om giltig)")
    p_login.add_argument("-v", "--verbose", action="store_true", help="visa feldetaljer")
    p_login.set_defaults(func=cmd_login)

    p_status = sub.add_parser("status", help="visa cache-plats och sessionsstatus (offline)")
    p_status.set_defaults(func=cmd_status)

    p_reg = sub.add_parser("register", help="registrera servern i Claude Code (--scope user)")
    p_reg.set_defaults(func=cmd_register)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    cmd = getattr(args, "command", None)
    # Inget subkommando ⇒ serve (så en bar `ica-mcp` i configen startar servern).
    if not cmd:
        return cmd_serve(args)
    if cmd != "serve":
        _enable_utf8_console()  # människo-läsbar output; serve äger sin egen stdout
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
