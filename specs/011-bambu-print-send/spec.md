# Feature Specification: Send a Print to a Bambu Lab Printer, with Confirmation

**Feature Branch**: `claude/011-bambu-print-send-07c5b3`

**Created**: 2026-11-23

**Status**: Draft

**Input**: User description: "Send a sliced file to a Bambu Lab printer and start it, after explicit confirmation." Full prompt: `specs/backlog.md`, section "Send a print to a Bambu Lab printer, with confirmation". Architecture: `docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §8 and §9.

## Clarifications

### Session 2026-11-23

- Q: When the spool loaded in an AMS slot does not match what the plate expects (other material, clearly different colour, empty slot or unknown spool), what must the confirmation do? → A: The confirmation requires the warnings to be explicitly acknowledged ("I have checked" in the UI, `acknowledge_warnings: true` in the API); otherwise it is refused.
- Q: Where does the sliced file sent to the printer come from? → A: Both: a sliced file stored on a model, or a file uploaded at send time (kept only for the life of the send, optionally attached to a model).
- Q: Which shop role is needed to prepare and confirm a print send? → A: Member, the role already required to control a printer (connect, pause, resume, stop).
- Q: How does Batchivo know a printer is in Developer Mode (the condition for showing "Send print")? → A: The operator declares it, and a "Test file transfer" button checks on demand that the printer accepts files, without blocking the save.
- Q: When a print started from Batchivo finishes, should the stock of the spools used move automatically? → A: No automatic movement: at the end, Batchivo proposes the deduction (the operator accepts or corrects it), and nothing is deducted on its own.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prepare a print and review its summary (Priority: P1)

An operator has sliced a model in Bambu Studio and has the sliced project
(`.gcode.3mf`). From a Bambu printer that is set up for sending, they choose
"Send print", pick the sliced file, pick one of its plates and say which AMS
slot feeds each filament the plate uses. Batchivo shows a summary before
anything reaches the printer: the printer, the file and plate, the estimated
print time and filament weight, and for each filament of the plate the slot it
will be drawn from, the spool Batchivo believes is loaded in that slot, and what
the printer itself reports in the slot. When the loaded spool does not match
what the plate expects (different material, clearly different colour, empty
slot, or no spool known), the summary says so next to that slot.

**Why this priority**: The summary is the safety net of the whole feature:
it is what the operator (or an agent) confirms. Without it nothing can be sent
safely, and on its own it already answers "is the right filament loaded for
this plate?".

**Independent Test**: With a mocked printer status and a sample sliced file,
prepare a send for plate 1 with a mapping where one slot holds the wrong
material, and check the summary lists the printer, plate, time, weight, each
slot's expected and loaded filament, and a mismatch warning on that slot; check
nothing was uploaded and no print command was sent.

**Acceptance Scenarios**:

1. **Given** a Bambu printer marked as in Developer Mode and connected, **When**
   the operator prepares a send of a sliced file, plate 2 and a slot mapping,
   **Then** they see the printer, file, plate 2, plate 2's estimated time and
   weight, and one line per filament of plate 2 with its mapped slot, the
   expected material and colour, and the spool known to be loaded there.
2. **Given** a slot whose loaded spool is PETG while the plate expects PLA,
   **When** the summary is prepared, **Then** that line carries a mismatch
   warning naming the expected and loaded material.
3. **Given** a sliced file that is not a Bambu sliced project (no plate G-code),
   **When** the operator prepares a send, **Then** the request is refused with
   a message saying the file must be sliced, and nothing is kept.
4. **Given** a plate number the file does not contain, **When** the operator
   prepares a send, **Then** the request is refused naming the plates available.
5. **Given** a prepared summary, **When** nothing else happens, **Then** no
   file has been sent to the printer and no print job exists for it.

---

### User Story 2 - Confirm the summary to start the print (Priority: P1)

Having reviewed the summary, the operator presses "Start print". Batchivo sends
the file to the printer and tells it to start that plate with that slot
mapping. A print job is recorded for the printer, linked to the model when the
file belongs to one, and from then on its status follows what the printer
reports (printing, finished, failed, cancelled). The confirmation is valid
only for the exact summary that was shown and only for a short time; after
that the operator has to prepare again. An agent goes through exactly the
same two steps: it cannot start a print without a confirmation of a summary.

**Why this priority**: Starting the print is the point of the feature, and the
confirmation rule is the main constraint of the backlog entry.

**Independent Test**: With mocked file transfer and printer messages, confirm
a prepared summary and check the file was sent, the start command named the
right file, plate and slot mapping, a print job exists in "printing", and a
later "finished" status from the printer moves the job to completed. Repeat
the confirmation and check it is refused.

**Acceptance Scenarios**:

1. **Given** a prepared summary less than the confirmation window old, **When**
   the operator confirms it, **Then** the file is sent, the print is started
   with the plate and slot mapping of the summary, and a print job in
   "printing" is linked to the printer (and to the model, when known).
2. **Given** a summary older than the confirmation window, **When** the
   operator confirms it, **Then** the confirmation is refused as expired,
   nothing is sent, and the operator is invited to prepare again.
3. **Given** a summary already confirmed once, **When** the same confirmation
   is sent again, **Then** it is refused and no second print starts.
4. **Given** a summary carrying a mismatch warning, **When** the operator
   confirms without acknowledging the warnings, **Then** the confirmation is
   refused, nothing is sent, and the same summary can still be confirmed with
   the acknowledgement within its window.
5. **Given** a confirmation for a summary prepared by another shop, **When** it
   is sent, **Then** it is refused as not found.
6. **Given** the file transfer fails part-way, **When** the operator confirms,
   **Then** no print command is sent, no print job is left in "printing" or
   "queued", the operator sees why it failed, and they can prepare again.
7. **Given** the file was sent but the printer cannot be told to start (the
   printer went offline), **When** the operator confirms, **Then** no print job
   is left as started, the operator sees the failure, and the sent file is
   cleaned up on a best-effort basis.
8. **Given** a started print, **When** the printer reports it finished, failed
   or was stopped, **Then** the print job moves to completed, failed or
   cancelled with the time it ended.
9. **Given** no confirmation call, **When** any other route of the system is
   used, **Then** there is no way to start a print on a Bambu printer.

---

### User Story 3 - Set a printer up for sending, understanding Developer Mode (Priority: P2)

On a Bambu printer's connection settings, the operator finds a "Developer
Mode" setting with a plain explanation: sending prints from Batchivo needs the
printer in LAN mode with Developer Mode turned on on the printer itself, which
disables Bambu cloud access (Bambu Handy, cloud printing from Bambu Studio);
without it, prints are sent with Bambu Studio or Bambu Connect as before. The
operator states that the printer is in Developer Mode. Only then does "Send
print" appear for that printer; on any other printer it is not shown and the
API refuses to prepare a send.

**Why this priority**: Required for the send to be reachable, but it is a
setting and an explanation, valuable only once story 1 and 2 exist.

**Independent Test**: Open the connection settings of a Bambu LAN printer,
read the explanation, turn the Developer Mode setting on, and check "Send
print" appears; turn it off and check it disappears and a prepare request is
refused.

**Acceptance Scenarios**:

1. **Given** a Bambu LAN printer, **When** the operator opens its connection
   settings, **Then** they see the Developer Mode setting and an explanation of
   what it enables and what it disables.
2. **Given** a printer with Developer Mode off (or a cloud, Moonraker, manual
   or unconnected printer), **When** the operator views it, **Then** no "Send
   print" action is shown, and a prepare request for it is refused with a
   message explaining Developer Mode is required.
3. **Given** a printer with Developer Mode on, **When** the operator views
   it, **Then** "Send print" is available.
4. **Given** a Bambu LAN printer, **When** the operator presses "Test file
   transfer", **Then** they see whether the printer accepted the connection
   or why it did not, and the Developer Mode setting can be saved either way.

---

### User Story 4 - Accept the spool deduction a finished print proposes (Priority: P3)

When a print sent from Batchivo ends, the print job shows a proposed stock
deduction: one line per spool used, with the weight the sliced file expected.
The operator accepts it as is, corrects an amount (for example after a failed
print that used only part of the filament), or dismisses it. Only on accept
does the spools' stock move, with an entry in each spool's history naming the
print job.

**Why this priority**: Keeps stock honest without letting a printer report
move it on its own; useful only once prints can be sent and followed.

**Independent Test**: Move a sent print's job to completed through a mocked
printer report, check a pending proposal lists each mapped spool with the
plate's expected weight and that no spool's weight changed; accept with one
amount corrected and check each spool's weight and history; check a second
accept is refused.

**Acceptance Scenarios**:

1. **Given** a sent print that the printer reports finished, **When** the
   operator opens the print job, **Then** they see a proposed deduction per
   mapped spool, and no spool weight has changed.
2. **Given** a pending proposal, **When** the operator accepts it with one
   amount corrected, **Then** each spool's weight drops by the accepted amount
   and its history shows a usage entry naming the print job.
3. **Given** a pending proposal, **When** the operator dismisses it, **Then** no
   stock moves and the proposal is closed.
4. **Given** an accepted or dismissed proposal, **When** it is accepted again,
   **Then** the request is refused and stock does not move twice.
5. **Given** a slot mapped to the external spool holder or to a slot with no
   spool known, **When** the proposal is built, **Then** that filament is listed
   without a spool and cannot be deducted until the operator picks one or
   leaves it out.

---

### Edge Cases

- The printer is already printing or paused: the prepare step warns, and the
  confirmation is refused while the printer is busy, so a running print is
  never replaced.
- The printer is not connected (no live status): prepare still builds the
  summary from Batchivo's slot mapping, marks the printer's own slot reports as
  unknown, and confirmation is refused until the printer is reachable.
- A plate uses more filaments than there are mapped slots, or two filaments
  are mapped to the same slot: prepare is refused with the offending filament.
- A plate is mapped to the external spool holder instead of an AMS slot: allowed,
  shown as "external spool" with no AMS check.
- A slot has no spool recorded in Batchivo: shown as "unknown spool" with a
  warning, not a refusal.
- Mismatches do not block the confirmation outright, but a summary carrying
  any warning can only be confirmed with an explicit acknowledgement of its
  warnings; without it the confirmation is refused and the reference stays
  usable within its window. The confirmed send records the warnings that were
  acknowledged.
- The file is very large: the size limit is the one already applied to model
  files.
- Two operators prepare sends to the same printer: each summary is
  independent; the first confirmation starts the print and the second is
  refused because the printer is then busy.
- The printer's access code changes between prepare and confirm: the
  confirmation uses the current connection settings.
- The operator's role is too low to control printers: prepare and confirm are
  refused.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST let an operator, or an API client acting with the
  operator's rights, prepare a print send for a Bambu printer by giving a
  sliced Bambu project file, a plate number and a mapping from each filament
  of the plate to an AMS slot or the external spool holder.
- **FR-002**: Preparing MUST NOT send anything to the printer and MUST NOT
  create a print job.
- **FR-003**: The prepared summary MUST show the printer, the file name, the
  plate, the plate's estimated print time and filament weight as recorded in
  the sliced file, and for each filament of the plate: its expected material
  and colour, the slot it is mapped to, the spool Batchivo has mapped to that
  slot, and what the printer last reported in that slot when known.
- **FR-004**: The summary MUST flag each slot where the loaded spool does not
  match the plate's expectation: different material, clearly different colour,
  empty slot, or no spool known; and MUST flag a printer that is busy or not
  reachable.
- **FR-004a**: When the summary carries at least one warning, the confirmation
  MUST include an explicit acknowledgement of the warnings (a "I have checked"
  tick in the web app, an `acknowledge_warnings` flag set to true in the API);
  a confirmation without it MUST be refused, without consuming the
  confirmation reference and without contacting the printer.
- **FR-005**: Preparing MUST return a confirmation reference valid for a single
  use and for a limited window of 5 minutes, bound to the tenant, the printer,
  the file, the plate and the slot mapping of that summary.
- **FR-006**: A print MUST start only when the confirmation reference of a
  summary is presented within its window; an expired, already used, unknown or
  other-tenant reference MUST be refused without contacting the printer.
- **FR-007**: The confirmation MUST NOT accept any change to the file, plate or
  mapping; a different send needs a new summary.
- **FR-008**: On confirmation the system MUST transfer the file to the printer,
  then instruct it to print the confirmed plate with the confirmed slot
  mapping, and record a print job assigned to that printer, linked to the
  model when the file is a model's file.
- **FR-009**: If the transfer or the start instruction fails, the system MUST
  NOT leave a print job in a queued or printing state, MUST report the cause,
  and MUST leave the confirmation reference consumed (a new prepare is needed).
- **FR-010**: After the start, the print job's status MUST follow the
  printer's reported state: printing while it prints, completed when it
  finishes, failed on a print failure, cancelled when stopped, with the end
  time recorded.
- **FR-011**: The confirmation MUST be refused while the printer reports it is
  printing or paused, or when the printer is not connected.
- **FR-020**: When a print started from a confirmed send finishes (completed,
  or failed/cancelled part-way), the system MUST propose a stock deduction for
  each spool mapped to a slot of the confirmed plate, with the weight the sliced
  file expected for that filament as the proposed amount. Nothing MUST be
  deducted until the operator accepts the proposal; the operator MUST be able
  to correct each amount before accepting, or dismiss the proposal. An accepted
  proposal MUST be recorded through the existing inventory transaction trail
  (one usage entry per spool, naming the print job), exactly once.
- **FR-012**: A Bambu LAN printer connection MUST carry a "Developer Mode"
  setting, off by default, that the operator turns on to state the printer
  accepts sends; prepare and confirm MUST be refused for printers where it is
  off or that are not Bambu LAN printers.
- **FR-012a**: The connection settings MUST offer a "Test file transfer"
  action for a Bambu LAN printer that checks, on demand, that the printer's
  file service accepts a connection with the stored access code, and shows
  success or the reason for failure. Its result MUST NOT block saving the
  Developer Mode setting, and the test MUST NOT leave a file on the printer.
- **FR-013**: The printer connection settings page MUST explain what Developer
  Mode enables (sending prints from Batchivo) and disables (Bambu cloud access,
  Bambu Handy, cloud sending), and the alternative (Bambu Studio or Bambu
  Connect).
- **FR-014**: The "Send print" action MUST be shown only for printers with
  Developer Mode on.
- **FR-015**: The operator MUST be able to pick the file either from a model's
  stored sliced files or by uploading a sliced file at send time. An uploaded
  file MUST be kept only for the life of the send (deleted once the summary
  expires or the send ends), unless the operator chooses to attach it to a
  model, in which case it becomes one of that model's files.
- **FR-016**: The summary and the confirmed send MUST be scoped to the tenant;
  one shop can never see, confirm or start another shop's send.
- **FR-017**: The printer access code MUST be read through a single point in
  the system, so a later change that stores it encrypted does not touch the
  send logic; the access code MUST never be logged or returned.
- **FR-018**: The confirmed print job MUST keep what was confirmed (file, plate,
  slot mapping, warnings acknowledged, who confirmed and when) so the operator can see
  later exactly what was started.
- **FR-019**: Prepare and confirm MUST require the Member role (the role
  already required to connect, pause, resume and stop a printer); a lower role
  MUST be refused. API clients acting for the operator get the same rule.

### Key Entities

- **Print send (prepared summary)**: a short-lived record of one prepared send:
  tenant, printer, file, plate, slot mapping, the summary shown (time, weight,
  per-slot expected and loaded filament, warnings), who prepared it, when it
  expires, and whether and when it was confirmed and with what outcome
  (started, transfer failed, start failed). It carries the confirmation
  reference.
- **Print job** (existing): gains a link to the send that started it, from
  which the confirmed file, plate and mapping are visible.
- **Printer connection** (existing): gains the Developer Mode setting.
- **AMS slot mapping** (existing): the spool Batchivo believes is in each slot,
  read for the summary.
- **Spool deduction proposal**: attached to a finished sent print: per spool,
  the proposed and the accepted weight, its status (pending, accepted,
  dismissed), who decided and when.
- **Inventory transaction** (existing): the spool history an accepted proposal
  writes to.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator goes from "Send print" on a printer to a started print
  in under 1 minute for a file already stored on a model.
- **SC-002**: 100% of prints started from Batchivo, from the web app or the
  API, pass through a confirmed summary; no route starts a print without one.
- **SC-003**: Every filament mismatch between the plate and a mapped slot that
  Batchivo knows about is shown on the summary before confirmation.
- **SC-004**: After a failed file transfer or start instruction, zero print jobs
  are left in a queued or printing state.
- **SC-005**: A started print's job reaches "completed", "failed" or
  "cancelled" within one printer status message of the printer reporting it.

- **SC-006**: Zero spool stock movements happen from a finished print without
  an operator's acceptance, and an accepted proposal moves each spool exactly
  once.

## Assumptions

- Developer Mode cannot be detected reliably from the printer, so the operator
  declares it on the connection and can check it with the on-demand transfer
  test; a printer that refuses the transfer despite the setting surfaces as a
  transfer failure at confirmation.
- Only Bambu LAN connections can send; cloud connections are out of scope (the
  cloud path needs Bambu's authorization flow).
- The file transfer uses the printer's local secure file service with the same
  access code as the status connection.
- Default print options are the slicer's: bed levelling and flow calibration
  on, timelapse off; changing them is out of scope.
- Estimated time and weight come from the sliced file's own metadata (the
  existing 3MF metadata reader), not from a new calculation.
- The confirmation window is 5 minutes.
- Encryption of the access code is out of scope (feature 009 adds it); this
  feature reads the code through one access point that 009 will switch.
- Exposure to AI agents (MCP, "print" scope) is feature 010; the two-step API is
  designed so an agent calls it exactly as the web app does.
- A print job started from an uploaded file not attached to a model has no
  model link; it keeps the file name and plate in what was confirmed.
