# Minimal MCP Server Template

A complete, deployable **Model Context Protocol** server with Streamable HTTP.

## Tools

| Tool | Description |
|------|-------------|
| `ping` | Returns `pong` |
| `add` | Adds two numbers |
| `echo` | Echoes a string |

## Run locally

```bash
cd templates/minimal-mcp-server
pip install -e .
uvicorn minimal_mcp.server:app --reload --port 8000
```

- Health: http://localhost:8000/health  
- MCP: http://localhost:8000/mcp/  

Optional secret path:

```bash
export MCP_PATH_SECRET=mysecret
# MCP URL becomes http://localhost:8000/mcp/mysecret/
```

## Deploy (Render / Fly / Docker)

```bash
docker build -t minimal-mcp .
docker run -p 8000:8000 -e MCP_PATH_SECRET=mysecret minimal-mcp
```

On Render: connect this folder (or monorepo root with Dockerfile path set), set `MCP_PATH_SECRET`.

## Connect a client

**Claude (remote connector):**  
`https://YOUR-HOST/mcp/YOUR_SECRET`

**Local stdio clients** need a different entrypoint; this template is HTTP-first for remote agents.

## Extend

1. Add `@mcp.tool()` functions in `server.py`
2. Redeploy
3. Client rediscovers tools automatically

## Production checklist

- [ ] Set `MCP_PATH_SECRET`
- [ ] HTTPS only
- [ ] Add OAuth if the client requires it (see main FPL server)
- [ ] Pin `mcp==1.28.1` (or your chosen version)
