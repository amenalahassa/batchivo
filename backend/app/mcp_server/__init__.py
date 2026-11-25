"""Batchivo MCP server for AI agents (spec 010).

A separate stdio process (`python -m app.mcp_server`) that calls Batchivo's own
REST API with a personal API token. It never touches the database or any other
backend module: tenant isolation, roles and validation stay exactly those of
the web app. Nothing under `app.*` outside this package may be imported here.
"""
