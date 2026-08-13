# Create your own MCP server

Everything you need is in this repo.

## Option A — Use the FPL server (already built)

Live URL:

```text
https://fpl-mcp-server-kaol.onrender.com/mcp/7c44fda3d43249e708e4e38b70e3561e
```

Agent brain: `agent/SYSTEM_PROMPT.md`

## Option B — Start from the minimal template

```bash
cp -r templates/minimal-mcp-server my-new-mcp
cd my-new-mcp
pip install -e .
uvicorn minimal_mcp.server:app --reload --port 8000
```

Then:

1. Add tools with `@mcp.tool()` in `src/minimal_mcp/server.py`
2. Deploy with the included `Dockerfile`
3. Point an MCP client at `https://your-host/mcp/<secret>`

## Option C — Learn the pattern from FPL

| File | Role |
|------|------|
| `src/fpl_server/mcp_tools.py` | Tools |
| `src/fpl_server/remote_main.py` | HTTP + OAuth + routes |
| `src/fpl_server/oauth.py` | OAuth provider |
| `Dockerfile` | Render deploy |

## Official docs

- https://modelcontextprotocol.io
- https://github.com/modelcontextprotocol/python-sdk
