"""Launch an unchanged production STDIO entry point with test-only SDK replacements."""

import runpy
import sys

from network_guard import install as install_network_guard
from providers import install

install_network_guard()

role = sys.argv[1]
if role not in {"evidence", "web_search", "workspace"}:
    raise SystemExit("Invalid fixture server role")
install(role)
sys.argv = [f"veridex.mcp.servers.{role}"]
runpy.run_module(sys.argv[0], run_name="__main__")
