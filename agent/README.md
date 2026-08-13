# FPL Football Manager Agent

## Quick start (Grok)

1. Read `GROK_AGENT.md`
2. Use `SYSTEM_PROMPT.md` as the agent brain in a Grok chat
3. MCP server (already live):  
   `https://fpl-mcp-server-kaol.onrender.com/mcp/7c44fda3d43249e708e4e38b70e3561e`

## Quick start (Claude)

1. Customize → connectors → add the MCP URL above  
2. Paste `SYSTEM_PROMPT.md` into project instructions  
3. Chat in that project

## Files

| File | Purpose |
|------|---------|
| `SYSTEM_PROMPT.md` | Full manager behaviour + tool map |
| `GROK_AGENT.md` | How to run the agent on Grok |
| `README.md` | This index |

## Build your own MCP server

See `templates/minimal-mcp-server/` for a complete minimal remote MCP server you can copy and extend.
