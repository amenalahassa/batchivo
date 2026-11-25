---
sidebar_position: 7
---

# MCP server for AI agents

Batchivo ships an **MCP server** so AI agents such as Claude Code can read and
update your shop: ideas, models and pinned notes, printers and AMS slots,
spools, print jobs and production runs, and (if you allow it) start prints.

The agent works **with your permissions and only the scopes you give it**. It
talks to Batchivo's own API with a personal API token, exactly like the web
app: it cannot see another shop, cannot do anything your role forbids, and
cannot touch your account, team, settings or payments.

## 1. Create a personal API token

1. In Batchivo, open **Settings → API tokens** and click **Create token**.
2. Give it a name you will recognise, e.g. *Claude Code – modelling PC*.
3. Choose its scopes:

   | Scope | What the agent may do |
   |---|---|
   | **Read** | List and read ideas, models, file versions, notes, printers, AMS slots, spools, print jobs, production runs, print sends |
   | **Write** | Create and change ideas (timeline, images, import, convert to a model) and pinned notes |
   | **AI generation** | Start and adopt AI generations (tools arrive with the AI generation feature) |
   | **Print** | Prepare and start prints on your Bambu printers. Never ticked by default. |

4. Choose when it expires: 30 days, 90 days, 1 year, or a date. **Every token
   expires, at most one year after creation**; create a new one when it does.
5. Click **Create token**. The token (`bvt_…`) is shown **once**: copy it now.
   Batchivo only keeps a fingerprint of it and cannot show it again.

The list then shows each token's name, the start of its value, its scopes,
expiry, **last use** and status (active, expired, revoked).

## 2. Add Batchivo to Claude Code

Put the token in an environment variable rather than in a file:

```powershell
setx BATCHIVO_API_TOKEN "bvt_xxxxxxxx_..."
```

(macOS/Linux: `export BATCHIVO_API_TOKEN=bvt_...` in your shell profile.)

Then add a `.mcp.json` file at the root of your modelling workspace:

```json
{
  "mcpServers": {
    "batchivo": {
      "command": "poetry",
      "args": ["-C", "/path/to/batchivo/backend", "run", "python", "-m", "app.mcp_server"],
      "env": {
        "BATCHIVO_API_URL": "https://api.batchivo.com",
        "BATCHIVO_API_TOKEN": "${BATCHIVO_API_TOKEN}"
      }
    }
  }
}
```

- `BATCHIVO_API_URL` is your Batchivo API address (`http://localhost:8000` for a
  local instance), without `/api/v1`.
- The server needs a checkout of the Batchivo repository with its backend
  dependencies installed (`cd backend && poetry install`). It never connects
  to the database: it only calls the API.

## 3. Check it works

Start Claude Code in the workspace and run `/mcp`: **batchivo** should be
connected. Ask *"list my ideas tagged kitchen"*. The tools listed depend on the
token's scopes: a read-only token shows no tool that writes or prints.

## Printing from an agent

With the **Print** scope, the agent first **prepares** a print (file, plate,
AMS slot per filament) and gets the same summary as the web dialog: estimated
time and weight, the spool expected and the spool loaded in each slot, and any
mismatch warning. Nothing reaches the printer at this step.

Starting the print is a separate tool, marked as destructive, so **Claude Code
asks you before running it**. Warnings are never acknowledged on your behalf:
if the summary has warnings, the print starts only when you explicitly accept
them. The confirmation expires after 5 minutes.

## Troubleshooting

| Message on start | What to do |
|---|---|
| `BATCHIVO_API_URL is not set` / `BATCHIVO_API_TOKEN is not set` | Set the variable (and restart Claude Code so it sees it). |
| `Batchivo refused the API token` | The token was revoked, has expired or was mistyped. Create a new one. |
| `Batchivo could not be reached at …` | Check the address and that Batchivo is running. |
| A tool answers `403: API token is missing the 'write' scope` | Create a token with that scope. |
| A tool answers `403: This endpoint does not accept API tokens` | That action is only available in the web app. |

The token is never printed by the server; logs show `bvt_****` instead.

## Lost or leaked token

Open **Settings → API tokens** and click **Revoke** on it. Every request made
with it is refused from that moment. Revoking cannot be undone; create a new
token for the agent.
