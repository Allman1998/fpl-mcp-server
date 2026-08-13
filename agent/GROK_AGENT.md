# Grok FPL Football Manager Agent

This is the Grok-side agent for the live FPL MCP server.

## What exists

| Piece | Location |
|-------|----------|
| Live MCP server | `https://fpl-mcp-server-kaol.onrender.com/mcp/7c44fda3d43249e708e4e38b70e3561e` |
| Behaviour prompt | `agent/SYSTEM_PROMPT.md` |
| This runbook | `agent/GROK_AGENT.md` |
| Minimal MCP template | `templates/minimal-mcp-server/` |

## How to run the agent with Grok

Grok does not currently offer Claude-style one-click remote MCP connectors.

**Supported mode:** use a Grok chat (this product) as the manager:

1. Open a dedicated chat with Grok
2. Paste `SYSTEM_PROMPT.md` as the first message or custom instructions if available
3. Say: “You are my FPL Football Manager. Use live data; ask for my Team ID if needed.”
4. For private squad tools, complete FPL login via the MCP OAuth flow in a client that supports it (e.g. Claude once), or provide Team ID for public data

## Team ID mode (works without private session)

Public FPL API covers:

- Bootstrap (players, teams, events)
- Fixtures
- Any entry’s public picks / history by Team ID

Private actions (authenticated transfers) need the MCP session on the server.

## Commands to try

- Review my team for this gameweek (Team ID: …)
- Best captain this week
- Transfer ideas under £8.0m midfielders
- Should I wildcard?

## Security

- Never commit API keys, FPL passwords, or Browserbase secrets
- Rotate keys shared in chat
