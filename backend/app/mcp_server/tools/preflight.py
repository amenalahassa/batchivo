"""Preflight tools: design briefs, typed notes, calibrations, test results (spec 009 over 010).

Every tool forwards to one 009 API call, which does every check (tenant, role,
intent schema, supersede rules, version/job consistency). Reading needs the
`read` scope; recording or changing anything needs `write`. Enumerations are
`Literal`s so the agent sees Preflight's own words in each input schema.
"""

from typing import Any, Literal, Optional

from mcp.server.mcpserver.exceptions import ToolError

from app.mcp_server.client import BatchivoClient
from app.mcp_server.tools.base import ToolSpec, call_api, read_tool, with_extra, write_tool

Step = Literal[
    "intent",
    "adopt",
    "clarify",
    "risk",
    "plan",
    "design",
    "check",
    "slice",
    "print",
    "test",
    "learn",
    "render",
    "ship",
    "quick",
]
StepStatus = Literal["not_started", "in_progress", "done", "skipped", "blocked"]
RiskClass = Literal["faible", "moyen", "élevé", "arrêt"]
RevisionPart = Literal["intent", "risk", "plan"]
NoteSource = Literal["person", "preflight", "print"]
Severity = Literal["info", "warning", "failure", "attention", "échec"]
NoteStatus = Literal["open", "resolved", "carried_forward", "dismissed"]
FitType = Literal["slide", "press", "snap", "print-in-place"]
Orientation = Literal["vertical", "horizontal"]
Provenance = Literal["measured", "assumed"]
TestKind = Literal["clearance_grid", "critical_zone", "full_part"]
Outcome = Literal["pass", "fail", "partial"]
Vector = list[float]


def _one_of(**ids: Optional[str]) -> tuple[str, str]:
    given = [(name, value) for name, value in ids.items() if value]
    if len(given) != 1:
        raise ToolError(f"Give exactly one of {', '.join(ids)}.")
    return given[0]


def build_tools(client: BatchivoClient) -> list[ToolSpec]:
    """The Preflight tool group."""

    # ------------------------------------------------------------ briefs

    async def get_design_brief(
        idea_id: Optional[str] = None,
        model_id: Optional[str] = None,
        brief_id: Optional[str] = None,
    ) -> Any:
        name, value = _one_of(idea_id=idea_id, model_id=model_id, brief_id=brief_id)
        path = {
            "idea_id": f"/ideas/{value}/design-brief",
            "model_id": f"/models/{value}/design-brief",
            "brief_id": f"/design-briefs/{value}",
        }[name]
        return await call_api(client.get(path))

    async def start_design_brief(
        idea_id: Optional[str] = None,
        model_id: Optional[str] = None,
        intent: Optional[dict[str, Any]] = None,
        intent_yaml: Optional[str] = None,
    ) -> Any:
        name, value = _one_of(idea_id=idea_id, model_id=model_id)
        owner = "ideas" if name == "idea_id" else "models"
        body = with_extra({"intent": intent, "intent_yaml": intent_yaml}, None)
        return await call_api(client.post(f"/{owner}/{value}/design-brief", json=body))

    async def update_design_brief(
        brief_id: str,
        intent: Optional[dict[str, Any]] = None,
        intent_yaml: Optional[str] = None,
        risk_class: Optional[RiskClass] = None,
        risk_md: Optional[str] = None,
        triage: Optional[dict[str, Any]] = None,
        plan_md: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
        params_yaml: Optional[str] = None,
        steps: Optional[dict[Step, StepStatus]] = None,
    ) -> Any:
        body = with_extra(
            {
                "intent": intent,
                "intent_yaml": intent_yaml,
                "plan_md": plan_md,
                "params": params,
                "params_yaml": params_yaml,
                "steps": steps,
            },
            None,
        )
        if risk_class is not None or risk_md is not None or triage is not None:
            # The risk part is replaced whole (risk.md, class and triage go together).
            body["risk"] = {"risk_class": risk_class, "risk_md": risk_md, "triage": triage}
        return await call_api(client.patch(f"/design-briefs/{brief_id}", json=body))

    async def list_design_brief_revisions(
        brief_id: str, part: Optional[RevisionPart] = None, skip: int = 0, limit: int = 50
    ) -> Any:
        params = {"part": part, "skip": skip, "limit": limit}
        return await call_api(client.get(f"/design-briefs/{brief_id}/revisions", params=params))

    # ------------------------------------------------------------ typed notes

    async def list_typed_notes(
        model_id: str,
        source: Optional[NoteSource] = None,
        severity: Optional[Severity] = None,
        status: Optional[NoteStatus] = None,
        file_id: Optional[str] = None,
        version_id: Optional[str] = None,
    ) -> Any:
        params = {
            "source": source,
            "severity": severity,
            "status": status,
            "file_id": file_id,
            "version_id": version_id,
        }
        return await call_api(client.get(f"/models/{model_id}/file-notes", params=params))

    async def add_typed_note(
        model_id: str,
        file_id: str,
        text: str,
        position: Vector,
        normal: Vector,
        severity: Severity,
        source: NoteSource = "preflight",
        rule_id: Optional[str] = None,
        measured_value: Optional[float] = None,
        expected_value: Optional[float] = None,
        value_unit: Optional[str] = None,
        layer: Optional[int] = None,
    ) -> Any:
        body = with_extra(
            {
                "text": text,
                "position": position,
                "normal": normal,
                "layer": layer,
                "source": source,
                "severity": severity,
                "rule_id": rule_id,
                # Sent as decimal strings, as value_mm is: the API keeps them exact.
                "measured_value": None if measured_value is None else str(measured_value),
                "expected_value": None if expected_value is None else str(expected_value),
                "value_unit": value_unit,
            },
            None,
        )
        return await call_api(client.post(f"/models/{model_id}/files/{file_id}/notes", json=body))

    async def dismiss_note(model_id: str, note_id: str, justification: str) -> Any:
        body = {"status": "dismissed", "dismissal_reason": justification}
        return await call_api(client.patch(f"/models/{model_id}/file-notes/{note_id}", json=body))

    # ------------------------------------------------------------ calibrations

    async def lookup_calibration(
        printer_id: str,
        fit_type: FitType,
        orientation: Orientation,
        material: Optional[str] = None,
        material_type_id: Optional[str] = None,
        filament_type_id: Optional[str] = None,
    ) -> Any:
        params = {
            "printer_id": printer_id,
            "fit_type": fit_type,
            "orientation": orientation,
            "material": material,
            "material_type_id": material_type_id,
            "filament_type_id": filament_type_id,
        }
        return await call_api(client.get("/calibrations/lookup", params=params))

    async def list_calibrations(
        printer_id: str,
        current_only: bool = False,
        fit_type: Optional[FitType] = None,
        orientation: Optional[Orientation] = None,
    ) -> Any:
        params = {
            "current_only": str(current_only).lower(),
            "fit_type": fit_type,
            "orientation": orientation,
        }
        return await call_api(client.get(f"/printers/{printer_id}/calibrations", params=params))

    async def export_atelier_calibrations(printer_id: Optional[str] = None) -> Any:
        return await call_api(
            client.get("/calibrations/atelier", params={"printer_id": printer_id})
        )

    async def record_calibration(
        printer_id: str,
        fit_type: FitType,
        orientation: Orientation,
        value_mm: float,
        provenance: Provenance,
        material: Optional[str] = None,
        material_type_id: Optional[str] = None,
        filament_type_id: Optional[str] = None,
        source_print_job_id: Optional[str] = None,
        source_test_result_id: Optional[str] = None,
        measured_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Any:
        body = with_extra(
            {
                "fit_type": fit_type,
                "orientation": orientation,
                # A string keeps the decimal exact on the way in.
                "value_mm": str(value_mm),
                "provenance": provenance,
                "material": material,
                "material_type_id": material_type_id,
                "filament_type_id": filament_type_id,
                "source_print_job_id": source_print_job_id,
                "source_test_result_id": source_test_result_id,
                "measured_at": measured_at,
                "notes": notes,
            },
            None,
        )
        return await call_api(client.post(f"/printers/{printer_id}/calibrations", json=body))

    # ------------------------------------------------------------ test results

    async def record_test_result(
        kind: TestKind,
        outcome: Outcome,
        model_id: Optional[str] = None,
        model_file_version_id: Optional[str] = None,
        print_job_id: Optional[str] = None,
        printer_id: Optional[str] = None,
        material: Optional[str] = None,
        filament_type_id: Optional[str] = None,
        orientation: Optional[Orientation] = None,
        measurements: Optional[list[dict[str, Any]]] = None,
        failure_mode: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Any:
        body = with_extra(
            {
                "kind": kind,
                "outcome": outcome,
                "model_id": model_id,
                "model_file_version_id": model_file_version_id,
                "print_job_id": print_job_id,
                "printer_id": printer_id,
                "material": material,
                "filament_type_id": filament_type_id,
                "orientation": orientation,
                "measurements": measurements,
                "failure_mode": failure_mode,
                "notes": notes,
            },
            None,
        )
        return await call_api(client.post("/print-test-results", json=body))

    async def update_test_result(
        result_id: str,
        outcome: Optional[Outcome] = None,
        measurements: Optional[list[dict[str, Any]]] = None,
        failure_mode: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Any:
        body = with_extra(
            {
                "outcome": outcome,
                "measurements": measurements,
                "failure_mode": failure_mode,
                "notes": notes,
            },
            None,
        )
        return await call_api(client.patch(f"/print-test-results/{result_id}", json=body))

    async def upload_test_result_photo(result_id: str, file_path: str) -> Any:
        return await call_api(
            client.upload(f"/print-test-results/{result_id}/photo", "file", file_path)
        )

    async def get_test_result(result_id: str) -> Any:
        return await call_api(client.get(f"/print-test-results/{result_id}"))

    async def list_test_results(
        model_id: Optional[str] = None,
        model_file_version_id: Optional[str] = None,
        print_job_id: Optional[str] = None,
        outcome: Optional[Outcome] = None,
        kind: Optional[TestKind] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Any:
        params = {
            "model_id": model_id,
            "model_file_version_id": model_file_version_id,
            "print_job_id": print_job_id,
            "outcome": outcome,
            "kind": kind,
            "skip": skip,
            "limit": limit,
        }
        return await call_api(client.get("/print-test-results", params=params))

    return [
        read_tool(
            "get_design_brief",
            "Get a part's Preflight design brief by idea, model or brief id: intent document "
            "(as written, with its validation: placeholders to clarify, values still inferred), "
            "risk class and summary, triage, plan, parameters and the status of each step. A "
            "model converted from an idea reaches the idea's brief.",
            get_design_brief,
        ),
        write_tool(
            "start_design_brief",
            "Start the design brief of an idea or a model (returns the existing one if there "
            "is one), optionally with a first intent (`intent` object or `intent_yaml` text in "
            "Preflight's intent.yaml format, schema_version 1).",
            start_design_brief,
        ),
        write_tool(
            "update_design_brief",
            "Save any part of a design brief: intent (`intent` or `intent_yaml`), risk "
            "(`risk_class`, `risk_md`, `triage` together replace the risk part), `plan_md`, "
            "parameters (`params` or `params_yaml`) and step statuses, e.g. "
            "{'risk': 'done', 'plan': 'in_progress'}. Changed intent, risk and plan are kept "
            "as revisions.",
            update_design_brief,
        ),
        read_tool(
            "list_design_brief_revisions",
            "List the earlier intents, risk parts and plans of a design brief, newest first.",
            list_design_brief_revisions,
        ),
        read_tool(
            "list_typed_notes",
            "List the notes pinned on a model's files, filtered by source (person, preflight, "
            "print), severity (info, warning, failure; attention/échec accepted), status, file "
            "or version.",
            list_typed_notes,
        ),
        write_tool(
            "add_typed_note",
            "Pin a Preflight finding on a model file at a point (position and unit normal, in "
            "mm): severity (info, warning/attention, failure/échec), rule id from Preflight's "
            "kb (e.g. dfam.wall.extrusion-multiple), measured and expected values with unit.",
            add_typed_note,
        ),
        write_tool(
            "dismiss_note",
            "Dismiss an open note (an alert the operator chooses to ignore) with a written "
            "justification, which is kept.",
            dismiss_note,
        ),
        read_tool(
            "lookup_calibration",
            "The calibrated clearance per side for a printer, fit type, orientation and "
            "material (code like PLA, or id), preferring a filament-specific value; "
            "found=false means fall back to the generic rule.",
            lookup_calibration,
        ),
        read_tool(
            "list_calibrations",
            "List a printer's calibrations, current and superseded, newest first.",
            list_calibrations,
        ),
        read_tool(
            "export_atelier_calibrations",
            "Current calibrations in Preflight's atelier.yaml `calibrations:` format "
            "(printer, material, orientation, fit, value_mm, provenance, measured_at).",
            export_atelier_calibrations,
        ),
        write_tool(
            "record_calibration",
            "Record a fit value (clearance per side, mm) for a printer, material (and "
            "optionally filament), orientation and fit type; it supersedes the current value "
            "of that combination, which stays in the history. Values are never edited.",
            record_calibration,
        ),
        write_tool(
            "record_test_result",
            "Record a printed test piece's result (clearance grid, critical zone or full "
            "part): outcome pass/fail/partial, measurements, failure mode, notes. Name the "
            "print job or the model version (the version is required for a part test).",
            record_test_result,
        ),
        write_tool(
            "update_test_result",
            "Correct a test result's outcome, measurements, failure mode or notes.",
            update_test_result,
        ),
        write_tool(
            "upload_test_result_photo",
            "Attach a local photo (JPEG, PNG or WebP) to a test result, replacing any earlier one.",
            upload_test_result_photo,
        ),
        read_tool("get_test_result", "Get one print test result.", get_test_result),
        read_tool(
            "list_test_results",
            "List print test results, newest first, by model, version, print job, outcome or kind.",
            list_test_results,
        ),
    ]
