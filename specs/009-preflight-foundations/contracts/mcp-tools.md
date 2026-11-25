# MCP tools: preflight group (spec 009 over 010)

File `backend/app/mcp_server/tools/preflight.py`, `build_tools(client)`, appended to `GROUPS` in
`tools/__init__.py`. Each tool forwards to one API call (contracts/api.md) through `call_api`; the
API does every check. Read tools: scope `read`; write tools: scope `write`.

| Tool | Scope | API call |
|---|---|---|
| `get_design_brief(idea_id?, model_id?, brief_id?)` (exactly one) | read | GET brief |
| `start_design_brief(idea_id?, model_id?, intent?, intent_yaml?)` | write | POST start |
| `update_design_brief(brief_id, intent?, intent_yaml?, risk_class?, risk_md?, triage?, plan_md?, params?, params_yaml?, steps?)` | write | PATCH (risk fields grouped into `risk` when any is given) |
| `list_design_brief_revisions(brief_id, part?, skip, limit)` | read | GET revisions |
| `list_typed_notes(model_id, source?, severity?, status?, file_id?, version_id?)` | read | GET file-notes |
| `add_typed_note(model_id, file_id, text, position, normal, source="preflight", severity, rule_id?, measured_value?, expected_value?, value_unit?, layer?)` | write | POST note |
| `dismiss_note(model_id, note_id, justification)` | write | PATCH status dismissed |
| `lookup_calibration(printer_id, fit_type, orientation, material?, material_type_id?, filament_type_id?)` | read | GET lookup |
| `list_calibrations(printer_id, current_only=False, fit_type?, orientation?)` | read | GET printer calibrations |
| `export_atelier_calibrations(printer_id?)` | read | GET atelier |
| `record_calibration(printer_id, fit_type, orientation, value_mm, provenance, material?, material_type_id?, filament_type_id?, source_print_job_id?, source_test_result_id?, measured_at?, notes?)` | write | POST calibration |
| `record_test_result(kind, outcome, model_id?, model_file_version_id?, print_job_id?, printer_id?, material?, filament_type_id?, orientation?, measurements?, failure_mode?, notes?)` | write | POST result |
| `update_test_result(result_id, outcome?, measurements?, failure_mode?, notes?)` | write | PATCH result |
| `upload_test_result_photo(result_id, file_path)` | write | POST photo (multipart) |
| `get_test_result(result_id)` | read | GET result |
| `list_test_results(model_id?, model_file_version_id?, print_job_id?, outcome?, kind?)` | read | GET results |

Enumerations are `Literal` types (steps, statuses, severity incl. `attention`/`échec`, fit types,
orientations, provenance, kinds, outcomes) so the agent sees them in the input schema. Coverage is
checked by `tests/mcp_server/test_tool_coverage.py`, `test_tool_error_paths.py` and
`test_mcp_tools_reach_api.py`; the group's tests are `tests/mcp_server/test_tools_preflight.py`.
