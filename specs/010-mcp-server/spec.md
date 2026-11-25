# Feature Specification: Batchivo MCP Server for AI Agents

**Feature Branch**: `claude/mystifying-bardeen-acb21d`

**Created**: 2026-11-24

**Status**: Draft

**Input**: User description: "An MCP server so AI agents (Claude Code) can read and write Batchivo data." Full prompt: `specs/backlog.md`, section "Batchivo MCP server for AI agents". Architecture: `docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §7.

## Clarifications

### Session 2026-11-24

- Q: Who delivers the MCP tools for AI generation (008) and for design briefs and calibrations (009)? → A: (c) explicit minimum. 010 delivers the `genai` token scope and a server built from pluggable tool groups. If 008 merges before 010 converges, 010 adds the genai tools; otherwise 008 adds its tool group (`tools/genai.py` and its tests) when it merges. 009 adds the design-brief and calibration tools. plan.md documents the pattern.
- Q: May an agent holding a `print` token start a print itself (the 011 confirm step)? → A: Yes. The confirm tool is declared destructive so the agent's client asks the operator before running it, warnings are never acknowledged by default, and the `print` scope is a separate opt-in on the token.
- Q: Must personal API tokens expire? → A: Yes, expiry is mandatory and at most one year: 30, 90 or 365 days, or a custom date up to one year.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create, see and revoke a personal API token (Priority: P1)

An operator wants an AI agent to work on their shop's data. In Batchivo's
settings, on a new "API tokens" tab, they create a token: they give it a name
("Claude Code – modelling PC"), choose what it may do (read, write, genai,
print) and when it expires. Batchivo shows the token's secret value once, with
a copy button and a warning that it will not be shown again. The list of tokens
then shows each token's name, scopes, creation date, expiry, last use and
status (active, expired, revoked), never the secret. The operator can revoke a
token at any time; from that moment every request made with it is refused.

**Why this priority**: Without a token nothing else in this feature can reach
Batchivo. On its own it is already useful: any script can call the Batchivo API
with a revocable, limited credential instead of the operator's password.

**Independent Test**: Create a token with the read scope, check its secret is
shown once and is absent from the list; call a read endpoint with it (accepted),
call a write endpoint with it (refused for scope), revoke it, call the read
endpoint again (refused).

**Acceptance Scenarios**:

1. **Given** a signed-in member, **When** they create a token named "Agent" with
   scopes read and write expiring in 90 days, **Then** the secret is shown once
   and the list shows "Agent", read + write, the expiry date, "never used" and
   "active".
2. **Given** an existing token, **When** the operator reloads the tokens page,
   **Then** the secret is not shown anywhere and cannot be retrieved again.
3. **Given** an active token used for a request, **When** the operator looks at
   the list, **Then** its "last used" shows the time of that request.
4. **Given** an active token, **When** the operator revokes it, **Then** the next
   request made with it is refused as unauthenticated and the list shows
   "revoked".
5. **Given** a token whose expiry has passed, **When** a request is made with it,
   **Then** it is refused as unauthenticated and the list shows "expired".
6. **Given** two users of the same shop, **When** each opens the tokens tab,
   **Then** each sees and manages only their own tokens.

---

### User Story 2 - An agent reads Batchivo data through MCP (Priority: P1)

The operator adds the Batchivo MCP server to Claude Code using the setup
instructions and a read-scoped token. In a conversation, the agent lists the
shop's ideas, opens one with its timeline, lists models with their file
versions and pinned notes, lists printers with their AMS slots, lists spools,
and lists print jobs and production runs. Everything the agent sees is exactly
what the operator would see in the web app for the same shop.

**Why this priority**: Reading is the foundation of every agent workflow
(design review, production planning) and carries no risk of changing data.

**Independent Test**: Against a mocked Batchivo API, call each read tool and
check it sends the expected request with the token and returns the API's data;
check a tool call made with an expired or revoked token returns a clear
"token refused" error instead of data.

**Acceptance Scenarios**:

1. **Given** the MCP server started with a read-scoped token, **When** the agent
   asks for ideas tagged "kitchen", **Then** it receives the same ideas the web
   app's idea list shows for that filter.
2. **Given** a model with three file versions and two pinned notes, **When** the
   agent asks for the model's notes, **Then** it receives both notes with their
   version and status.
3. **Given** a token of shop A, **When** the agent asks for an idea of shop B by
   its identifier, **Then** it is told the idea does not exist.
4. **Given** the Batchivo API is unreachable, **When** the agent calls a tool,
   **Then** it receives an error saying Batchivo could not be reached, and the
   MCP server keeps running.

---

### User Story 3 - An agent writes ideas, models and notes (Priority: P2)

With a token that has the write scope, the agent records its work in Batchivo:
creates an idea, adds a timeline entry or an image to it, imports a research
report, converts an idea into a model, pins a note on a model file version,
resolves a note or carries it forward to a newer version.

**Why this priority**: This is what makes the agent a collaborator rather than
a reader, but it depends on reading and on tokens.

**Independent Test**: Against a mocked API, call each write tool and check the
request body and method; with a read-only token, check the same tool is refused
before any data changes.

**Acceptance Scenarios**:

1. **Given** a write-scoped token, **When** the agent creates an idea with a
   title and tags, **Then** the idea appears in the web app's idea list,
   created through the same validation as the web form.
2. **Given** a read-only token, **When** the agent tries to add a note, **Then**
   the request is refused with a message naming the missing "write" scope, and
   nothing is created.
3. **Given** a write-scoped token and invalid input (empty title), **When** the
   agent creates an idea, **Then** it receives the same validation message the
   web app would get.
4. **Given** a write-scoped token held by a user whose shop role is viewer,
   **When** the agent tries to create an idea, **Then** it is refused exactly as
   that user would be in the web app.

---

### User Story 4 - An agent prepares and starts a print (Priority: P3)

With a token that has the print scope, the agent prepares a print send on a
Bambu printer (file, plate, slot mapping) and gets back the same summary the
web dialog shows, including slot mismatch warnings. Starting the print is a
separate, explicit step that the agent's client presents to the operator for
approval before it runs, and it is refused if the warnings were not
acknowledged, exactly as in the web app.

**Why this priority**: Valuable for production but the highest-risk action; it
comes last and reuses the confirmation already built for the web app.

**Independent Test**: Against a mocked API, prepare a send and check the
summary is returned; confirm it and check the confirm request carries the
acknowledgement; with a token lacking the print scope, check both are refused.

**Acceptance Scenarios**:

1. **Given** a print-scoped token, **When** the agent prepares a send, **Then**
   it receives the summary with time, weight, slot lines and warnings, and
   nothing is sent to the printer.
2. **Given** a prepared send with a mismatch warning, **When** the agent
   confirms without acknowledging the warnings, **Then** the start is refused.
3. **Given** a token with read and write but not print, **When** the agent
   prepares or confirms a send, **Then** both are refused naming the missing
   "print" scope.

---

### User Story 5 - Set up the MCP server in Claude Code (Priority: P2)

The operator follows the operator documentation: create a token, add a
`.mcp.json` entry to the modelling workspace with the Batchivo address and the
token taken from an environment variable, start Claude Code and check the
Batchivo tools are listed.

**Why this priority**: Without setup instructions the feature is unusable by
the operator.

**Independent Test**: Follow the documented steps on a local instance and check
the agent can list ideas.

**Acceptance Scenarios**:

1. **Given** the documentation, **When** the operator copies the `.mcp.json`
   example and sets the token environment variable, **Then** Claude Code starts
   the Batchivo server and lists its tools.
2. **Given** the token variable is missing or empty, **When** the server starts,
   **Then** it stops with a message saying which variable to set, without
   printing any token.

---

### Edge Cases

- A token's secret appears in a request log, an error message or a crash
  report: it must not; the server and the MCP process replace it with a mask.
- A token is used after the user who created it has left the shop or been
  deactivated: refused.
- A token is used to create, list or revoke tokens, change a password, manage
  shop members or reach platform administration: refused, whatever its scopes.
- The operator gives a token no scope: refused at creation (at least one scope).
- An expiry date in the past, missing, or more than one year ahead: refused at
  creation.
- The same name used twice: allowed (names are labels, not identifiers).
- The MCP server receives a tool call whose scope the token lacks: the call
  reaches the API, which refuses it; the agent gets the refusal message.
- The API answers with an error (404, 409, 422): the agent receives the API's
  message, not a generic failure.
- A large list (hundreds of ideas or spools): tools pass the API's paging
  through; the agent asks for the next page explicitly.
- Idea images: the agent can fetch an idea entry's image with its token; an
  image of another shop is refused.

## Requirements *(mandatory)*

### Functional Requirements

**Personal API tokens**

- **FR-001**: A signed-in shop user MUST be able to create a personal API token
  with a name (1–100 characters), at least one scope among read, write, genai
  and print, and a mandatory expiry of 30, 90 or 365 days or a custom date at
  most one year ahead; a token without expiry or beyond one year MUST be
  refused.
- **FR-002**: The token's secret MUST be shown only once, in the creation
  response; Batchivo MUST store only a one-way hash of it and MUST NOT be able
  to show it again.
- **FR-003**: Users MUST be able to list their own tokens with name, scopes,
  creation date, expiry, last-used time and status (active, expired, revoked),
  and MUST NOT see other users' tokens.
- **FR-004**: Users MUST be able to revoke one of their tokens; revocation takes
  effect for the next request. A revoked token MUST NOT be reactivated.
- **FR-005**: A token MUST act as its owner within the token's shop: the owner's
  shop role applies in full, and the token's scopes can only narrow it, never
  widen it.
- **FR-006**: A request made with a token MUST be refused as unauthenticated when
  the token is unknown, revoked, expired, or its owner no longer belongs to the
  shop or is inactive.
- **FR-007**: Scopes MUST be enforced by Batchivo's API, not only by the MCP
  server: read covers reading the resources listed in FR-012; write covers
  creating and changing them; genai covers starting and adopting AI generations;
  print covers preparing and confirming a print send and accepting or dismissing
  its consumption. A request outside the token's scopes MUST be refused with a
  message naming the missing scope.
- **FR-008**: A token MUST NOT be accepted for token management, sign-in,
  password and account changes, shop member management, billing and payments,
  shop settings, or platform administration, whatever its scopes.
- **FR-009**: Batchivo MUST record when each token was last used, at a precision
  of at least one minute.
- **FR-010**: A token's secret MUST NOT appear in any log, error message, trace
  or crash report of the API or the MCP server.
- **FR-011**: The existing sign-in for the web app MUST behave exactly as before;
  a web session MUST NOT be affected by tokens.

**MCP server**

- **FR-012**: The MCP server MUST offer tools for: ideas (list, get, list tags,
  create, update, add timeline entry, upload entry image, get entry image,
  import, parse report, convert); models (list, get), file versions (list) and
  pinned notes (list, add, update or resolve, carry forward); printers (list,
  get, AMS slots); spools (list, get); print jobs (list, get) and production
  runs (list, get); print sends (prepare, confirm, list, get).
- **FR-013**: Each tool MUST call Batchivo's own API with the token; the MCP
  server MUST NOT access the database, files or any other store directly.
- **FR-014**: Each tool MUST declare the scope it needs; the server MUST describe
  tools that write or start a print as such, so the agent's client can ask the
  operator before running them.
- **FR-015**: The confirm-print tool MUST be declared destructive (so the
  agent's client asks the operator before it runs), MUST take the warnings
  acknowledgement as an explicit argument defaulting to "not acknowledged", and
  MUST NOT acknowledge on the agent's behalf. The `print` scope MUST never be
  selected by default when creating a token.
- **FR-016**: Errors from the API MUST reach the agent with the API's status and
  message; an unreachable API MUST yield a clear error without stopping the
  server.
- **FR-017**: The MCP server MUST run locally over standard input/output, take
  the Batchivo address and token from its environment, and stop with a clear
  message (without echoing any secret) when either is missing.
- **FR-018**: The MCP server MUST be built from tool groups, one per domain, so
  that later features add their own group (generation jobs from the Generative AI
  layer, design briefs and calibrations from Preflight foundations) without
  changing existing tools or the token model. This feature delivers the `genai`
  scope and its enforcement; the genai tools are added by this feature only if
  the Generative AI layer is merged before this feature converges, otherwise by
  that feature; design-brief and calibration tools are added by Preflight
  foundations.

**Operator interface and documentation**

- **FR-019**: The settings page MUST gain an "API tokens" tab with the token
  list, a create dialog, the one-time secret display with copy, and revoke with
  confirmation. Other settings tabs MUST NOT change.
- **FR-020**: Operator documentation MUST explain creating a token, choosing
  scopes, the `.mcp.json` entry for Claude Code with the token in an environment
  variable, checking the tools are listed, and revoking a lost token.

### Key Entities

- **Personal API token**: belongs to one user in one shop; name, scopes, a hash
  of the secret and a short non-secret prefix to recognise it, creation time,
  expiry, last-used time, revocation time. Never stores the secret.
- **MCP tool**: a named operation offered to agents, mapped to one Batchivo API
  operation, with the scope it needs and whether it changes data.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can create a token and have Claude Code list ideas from
  their shop in under 5 minutes by following the documentation.
- **SC-002**: 100% of tool calls made with a token lacking the needed scope are
  refused by the API, verified by a test per scope.
- **SC-003**: A revoked or expired token is refused on the very next request in
  100% of tests.
- **SC-004**: No test, log or error output produced by the feature contains a
  token secret (checked by a test that searches captured output).
- **SC-005**: Every MCP tool has a test against a mocked API covering its request
  and its error path.
- **SC-006**: Existing web sign-in and every existing endpoint test pass
  unchanged.

## Assumptions

- Only shop users (members of a tenant) create tokens; storefront customers and
  platform administration are out of scope.
- Any shop role may create tokens for itself; what the token can do is bounded by
  that role (a viewer's write token still cannot write).
- The MCP server offers no delete tools in this feature (ideas, entries, notes,
  print jobs are deleted from the web app only).
- No cap on the number of tokens per user; the list shows them all.
- Only the streamable HTTP transport is deferred ("HTTP later"); this feature
  delivers the standard input/output transport.
- The print-send tools reuse the 011 prepare/confirm API unchanged; the 5-minute
  confirmation window and the warnings acknowledgement still apply.
- Generation jobs (008), design briefs and calibrations (009) are not on main
  yet; their tools depend on those APIs (see FR-018).
