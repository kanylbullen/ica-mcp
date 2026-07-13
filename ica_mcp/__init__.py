"""ica-mcp — MCP-server för ICA:s inköpslistor.

Publikt API: IcaClient (återanvändbar klient mot ICA:s inofficiella API).
CLI: `ica-mcp` (subkommandon serve/login/status/register), se cli.py.
"""

from __future__ import annotations

from .client import IcaAuthError, IcaClient, IcaError, resolve_state_file

__version__ = "0.4.0"
__all__ = ["IcaClient", "IcaError", "IcaAuthError", "resolve_state_file", "__version__"]
