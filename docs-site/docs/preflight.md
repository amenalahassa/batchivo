---
sidebar_position: 6
title: Preflight
---

# Preflight: design briefs, calibrations and test prints

**Preflight** is the method (and the Claude skill of the same name) for
anticipating design problems of a functional 3D-printed part before printing
it: what it must hold, how hot it gets, what it fits into, how it will be
tested. Batchivo keeps Preflight's records next to the idea, the model and the
printer they belong to, so the person at the screen and an AI agent work from
the same file.

Four things are kept:

| Record | Where you see it | What it holds |
|--------|------------------|---------------|
| **Design brief** | An idea's *Design brief* tab; a model's page | The part's intent, risk class and risk notes, plan, design parameters, and the status of each of Preflight's 14 steps |
| **Typed note** | The 3D viewer's notes | A note pinned on the part by Preflight (or a printer, or the slicer), with a severity, a rule and the measured versus expected value |
| **Calibration** | Printers page → *Calibrations* | A measured fit clearance (mm per side) for a printer, material, fit and orientation |
| **Test result** | A model's *Test prints* card | How a printed test piece did: outcome, measurements, failure mode, photo |

## Who can do what

| Role | Can |
|------|-----|
| Viewer | Read briefs, notes, calibrations and test results |
| Member and above | Start and edit briefs, dismiss notes, record calibrations and test results |

Deleting a brief is only possible signed in, never with an API token.

## Design brief

A brief starts on an idea or on a model. When an idea is turned into a model,
the model shows **the same brief** — there is never a copy to keep in step.

- **Steps.** Each of Preflight's steps (intent, adopt, clarify, risk, plan,
  design, check, slice, print, test, learn, render, ship, quick) is *not
  started*, *in progress*, *done*, *skipped* or *blocked*. Change one with its
  selector; it is saved at once.
- **Intent.** The simple fields (function, category, quantity, sales channel,
  country, success criteria) are a form. Loads, environment and interfaces
  are YAML or JSON text, each value with its status (`déduit`, `estimée`,
  `validé`, `mesurée`). Anything unknown stays `[À PRÉCISER]` — nothing is
  invented. Batchivo checks the intent exactly as Preflight's own validator
  does and lists what is still to clarify or to confirm.
- **Risk and plan.** Markdown, as Preflight writes `risk.md` and `plan.md`.
- **Parameters.** `params.yaml`, the design's current inputs.

Every saved intent, risk part and plan is kept: **History** shows the earlier
versions, newest first. They cannot be changed.

## Typed notes

A note Preflight pins on the part shows a **Warning** or **Failure** badge,
the rule it comes from (for example `fit.slide.clearance`) and, when it has
one, the measured and expected values. Filter the notes by source and
severity.

A note you accept as it is can be **dismissed**: you must say why. A
dismissed note keeps its reason, who dismissed it and when, even after it is
reopened. Notes written by people look exactly as before.

## Calibrations

On the Printers page, **Calibrations** shows the clearances in force for that
printer, one per material, fit (slide, press, snap, print-in-place) and
orientation, with the history of earlier values.

Record a new value to replace one: the old value is kept, marked as
superseded, and never edited. Values are exact to the micron (`0.150 mm`).
When Preflight computes a clearance, it uses the filament's value if there is
one, else the material's, else its generic rule.

## Test prints

A model's **Test prints** card starts with one line: how many failure notes
are still open, and how the last test went on which version. Record a test
with its kind (clearance grid, critical zone, full part), outcome, the version
tested, measurements, failure mode and an optional photo. A critical-zone or
full-part test must name the version it tested. Photos are only shown to
people signed in to your shop.

## Printer secrets

Printer access codes and cloud tokens are stored encrypted. If the server's
key changes, a stored code can no longer be read: the printer's connection
dialog says so, and you enter the code again.

## For AI agents

Every action above is available to an agent through the
[MCP server](./mcp.md) and the REST API, with a personal API token: reading
needs the `read` scope, recording or changing needs `write`.
