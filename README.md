# ica-mcp

An **MCP server for ICA** — Sweden's largest grocery chain — that lets AI agents
(Claude, or any [Model Context Protocol](https://modelcontextprotocol.io) client)
read and edit your ICA shopping lists in natural language:

> *"What's on my shopping list?"* · *"Add coffee and bananas to the Willys list"* ·
> *"Check off milk"* · *"Clear the checked items"*

ICA has no official public API. This server talks to the same private backend the
ICA mobile app uses, authenticating with your **personnummer + password** (no
BankID required for accounts that support password login).

> ⚠️ **Unofficial & unaffiliated.** This project is not affiliated with, endorsed
> by, or supported by ICA. It relies on a private, undocumented API that can change
> or break at any time, and using it may be against ICA's terms of service. Use at
> your own risk, for personal use only.

## Tools

| Tool | What it does |
|---|---|
| `list_shopping_lists` | All your lists + how many items remain/checked |
| `view_shopping_list` | Contents of a list (by name; defaults to your primary list) |
| `add_items` | Add one or more free-text items to a list |
| `check_off` / `uncheck` | Mark an item bought / undo |
| `remove_item` | Remove an item entirely |
| `clear_checked` | Remove all checked items (tidy up after shopping) |
| `create_shopping_list` / `delete_shopping_list` | Create / delete a list |
| `list_saved_recipes` / `get_recipe` | Your favourite recipes; one recipe's ingredients + steps |
| `random_recipes` | Random recipes for inspiration |
| `add_recipe_to_shopping_list` | Add a recipe's ingredients to a list as free-text items |
| `list_stores` / `get_offers` | Your favourite stores; current offers for a store |
| `get_bonus` | Your ICA bonus / Stammis balance |

Lists, items and stores are referenced **by name**, so an agent can act on
natural language. Omitting a list/store name targets your primary one (the
`Handla` list / your first favourite store).

## Requirements

- **Python 3.10+**
- **A Swedish egress IP.** ICA's API gateway (`apimgw-pub.ica.se`) returns
  HTTP 451 to non-Swedish IPs. Run this on a machine/network in Sweden — a
  US/DE VPS will not work.
- An **ICA account that logs in with personnummer + password** (accounts locked
  to BankID-only are not supported).

## Setup

Everything is one `ica-mcp` command with four subcommands:

| Command | What it does |
|---|---|
| `ica-mcp login` | Log in once (personnummer + password) and cache the session |
| `ica-mcp register` | Register the server with Claude Code (`--scope user`) |
| `ica-mcp status` | Show the cache location + whether the session is valid (no login) |
| `ica-mcp serve` | Run the MCP server over stdio — what your client launches |

### 1. Install

The quickest path uses [uv](https://docs.astral.sh/uv/) — one command, identical
on Windows, macOS and Linux:

```bash
# (only if you don't have uv yet)
#   Windows:      winget install --id=astral-sh.uv -e
#   macOS/Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh

uv tool install git+https://github.com/kanylbullen/ica-mcp
uv tool update-shell      # puts `ica-mcp` on PATH — then open a NEW terminal
```

<details>
<summary>Fallback without uv (plain pip + venv)</summary>

```bash
git clone https://github.com/kanylbullen/ica-mcp.git
cd ica-mcp
python3 -m venv .venv
.venv\Scripts\pip install .      # Windows
.venv/bin/pip install .          # macOS / Linux
```

Then use the venv's `ica-mcp` in place of the bare command below:
`.venv\Scripts\ica-mcp.exe` (Windows) or `.venv/bin/ica-mcp` (macOS/Linux).
</details>

### 2. Log in (once)

```bash
ica-mcp login          # prompts for personnummer + password (hidden)
```

On success it prints your name and lists and caches the session (OAuth client +
tokens) in a **per-user state dir** — `%LOCALAPPDATA%\ica-mcp` (Windows),
`~/.local/state/ica-mcp` (Linux), `~/Library/Application Support/ica-mcp` (macOS).
The short-lived access token (~15 min) is auto-refreshed via the long-lived
refresh token, so you normally log in only once. Verify anytime:

```bash
ica-mcp status         # cache path + session validity, without logging in
```

### 3. Register with your MCP client

**Claude Code** — let the CLI do it (writes at user scope, resolving the right path):

```bash
ica-mcp register
```

Registering at `--scope user` sidesteps a Windows drive-letter project-key quirk.
If the `claude` CLI isn't found, `register` prints a ready-to-paste `mcp.json`.
The equivalent manual command is:

```bash
claude mcp add ica --scope user -- ica-mcp serve
```

**Any other MCP client** (`mcp.json`):

```json
{
  "mcpServers": {
    "ica": {
      "command": "ica-mcp",
      "args": ["serve"]
    }
  }
}
```

If `ica-mcp` isn't on PATH, use the absolute path uv printed at install, or
`python -m ica_mcp serve`.

Restart your MCP client and the tools appear. The server reads the cached session,
so it needs no credentials in its environment. If the refresh token ever expires,
re-run `ica-mcp login` — or set `ICA_USER` / `ICA_PASS` (see `.env.example`) so
`serve` can re-authenticate unattended. Relocate the cache with `ICA_STATE_FILE`.

## How authentication works

ICA migrated (around 2024) from a simple Basic-auth API to an OAuth 2.0 / OIDC
flow backed by a [Curity](https://curity.io) Identity Server at
`ims.icagruppen.se`, with the data API behind an F5 gateway at
`apimgw-pub.ica.se`. The flow is:

1. bootstrap client-credentials token (`scope=dcr`)
2. dynamic client registration (`POST /register`) → per-install client
3. PKCE authorize → HTML login form
4. `POST /authn/authenticate/IcaCustomers` with personnummer + password
5. exchange the resulting code for a Bearer access/refresh token

The auth flow is a standalone port of the excellent
[**LazyTarget/ha-ica-todo**](https://github.com/LazyTarget/ha-ica-todo) Home
Assistant integration — full credit for reverse-engineering the current flow.
The hardcoded DCR bootstrap client id/secret are ICA **app** constants (also
public in that project), not user secrets.

## Security & privacy

- Tokens are cached in a per-user state dir (see *Log in*), outside the repo,
  `chmod 0600` on POSIX. On **Windows** that only toggles the read-only bit, so
  the file is not OS-ACL-protected there — treat the machine account as the
  trust boundary. Set `ICA_STATE_FILE` to relocate the cache.
- **No `keyring` dependency by design.** The Swedish-egress requirement pushes
  many users onto headless homelab/VPS boxes that lack a Secret Service /
  Credential Manager; a portable `0600` file is the deliberate choice.
- Nothing is logged to stdout (stdout is reserved for the MCP protocol — logs go
  to stderr).
- This server can **modify your real ICA account** (add/remove items, delete
  lists). Write operations were validated against throwaway lists during
  development.

## Roadmap

Done: **shopping lists** (phase 1), **recipes + offers + bonus** (phase 2,
including the composite *"add a recipe's ingredients to my shopping list"*).

Planned next, on the same auth:

- **Recipe search** by phrase (the search endpoint shape isn't nailed down yet)
- **Product / EAN lookup** (`productservice/v1/product/{ean}`)
- **Personal offers** across stores

## Credits

- Auth flow ported from [LazyTarget/ha-ica-todo](https://github.com/LazyTarget/ha-ica-todo)
- Historical API reference: [svendahlstrand/ica-api](https://github.com/svendahlstrand/ica-api)
  (documents the now-defunct `handla.api.ica.se` backend)

## License

MIT — see [LICENSE](LICENSE).
