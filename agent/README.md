# FPL Football Manager Agent

Agent definition for use with the live FPL MCP server.

## Connect (Claude)

1. Claude → **Customize** → connectors  
2. Add remote MCP:  
   `https://fpl-mcp-server-kaol.onrender.com/mcp/7c44fda3d43249e708e4e38b70e3561e`  
3. Complete OAuth / FPL sign-in  
4. Paste the contents of `SYSTEM_PROMPT.md` into the project or custom instructions for this agent  

## Connect (other MCP clients)

Point the client at the same URL. Use `SYSTEM_PROMPT.md` as the system prompt.

## Files

| File | Purpose |
|------|---------|
| `SYSTEM_PROMPT.md` | Full agent behaviour + tool map |
| `README.md` | How to attach the agent to the MCP server |

## Notes

- Public FPL data works without a personal session; **your squad** needs a successful FPL login on the server.  
- Do not commit secrets (Browserbase keys, tokens, passwords).  
