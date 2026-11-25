"""`python -m app.mcp_server`: run the Batchivo MCP server over stdio (spec 010)."""

import sys

from app.mcp_server.server import main

if __name__ == "__main__":
    sys.exit(main())
