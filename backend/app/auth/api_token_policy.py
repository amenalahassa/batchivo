"""Which endpoints accept a personal API token, and with which scope (spec 010, research R5).

Deny by default: an endpoint absent from `TOKEN_ROUTE_SCOPES` refuses every
token, whatever its scopes. Sign-in, accounts, members, token management,
settings, payments, platform, the shop and every DELETE stay JWT-only.

Keys are `(HTTP method, "<module>.<qualname>")` of the route's handler, read
from `request.scope["endpoint"]`: FastAPI includes routers lazily, so the path
a dependency sees is router-local and ambiguous, while the handler is unique.
A test resolves every key to a live route, so a renamed handler fails CI.

Extension (008, 009): add rows for your routes here, with scope `genai` for
starting or adopting a generation, `read` for reads, `write` for writes.
"""

from collections.abc import Callable, Iterator
from typing import Any, Literal, Optional

TokenScope = Literal["read", "write", "genai", "print", "any"]

#: `any`: reachable by every valid token, whatever its scopes.
ANY_SCOPE: TokenScope = "any"

_IDEAS = "app.api.v1.ideas"
_MODELS = "app.api.v1.models"
_FILES = "app.api.v1.model_files"
_VERSIONS = "app.api.v1.model_file_versions"
_NOTES = "app.api.v1.model_file_notes"
_PRINTERS = "app.api.v1.printers"
_BAMBU = "app.api.v1.printer_bambu"
_SENDS = "app.api.v1.print_sends"
_SPOOLS = "app.api.v1.spools"
_QUEUE = "app.api.v1.print_queue"
_RUNS = "app.api.v1.production_runs"
_TOKENS = "app.api.v1.api_tokens"
_GENAI = "app.api.v1.genai"
_BRIEFS = "app.api.v1.design_briefs"
_CALIBRATIONS = "app.api.v1.calibrations"
_TESTS = "app.api.v1.print_test_results"

TOKEN_ROUTE_SCOPES: dict[tuple[str, str], TokenScope] = {
    # Ideas (007)
    ("GET", f"{_IDEAS}.list_ideas"): "read",
    ("GET", f"{_IDEAS}.list_idea_tags"): "read",
    ("GET", f"{_IDEAS}.get_idea"): "read",
    ("GET", f"{_IDEAS}.list_entries"): "read",
    ("GET", f"{_IDEAS}.get_entry_image"): "read",
    ("POST", f"{_IDEAS}.create_idea"): "write",
    ("PATCH", f"{_IDEAS}.update_idea"): "write",
    ("POST", f"{_IDEAS}.create_entry"): "write",
    ("POST", f"{_IDEAS}.upload_entry_images"): "write",
    ("PATCH", f"{_IDEAS}.update_entry"): "write",
    ("POST", f"{_IDEAS}.start_iteration"): "write",
    ("POST", f"{_IDEAS}.import_ideas"): "write",
    # Persists nothing, but needs the member role: a read token may not spend server work on it.
    ("POST", f"{_IDEAS}.parse_pain_point_report"): "write",
    ("POST", f"{_IDEAS}.convert_idea"): "write",
    # Models, files, versions, pinned notes
    ("GET", f"{_MODELS}.list_models"): "read",
    ("GET", f"{_MODELS}.get_model"): "read",
    ("GET", f"{_FILES}.list_files"): "read",
    ("GET", f"{_VERSIONS}.list_file_versions"): "read",
    ("GET", f"{_NOTES}.list_file_notes"): "read",
    ("POST", f"{_NOTES}.create_file_note"): "write",
    ("PATCH", f"{_NOTES}.update_file_note"): "write",
    ("POST", f"{_NOTES}.carry_file_note_forward"): "write",
    # Printers and AMS
    ("GET", f"{_PRINTERS}.list_printers"): "read",
    ("GET", f"{_PRINTERS}.get_printer"): "read",
    ("GET", f"{_BAMBU}.get_printer_status"): "read",
    ("GET", f"{_BAMBU}.list_ams_slots"): "read",
    # Spools
    ("GET", f"{_SPOOLS}.list_spools"): "read",
    ("GET", f"{_SPOOLS}.get_spool"): "read",
    # Print jobs and production runs (read only)
    ("GET", f"{_QUEUE}.list_print_jobs"): "read",
    ("GET", f"{_QUEUE}.get_print_job"): "read",
    ("GET", f"{_RUNS}.list_production_runs"): "read",
    ("GET", f"{_RUNS}.get_production_run"): "read",
    # Print sends (011): reading is `read`; preparing, starting and the spool
    # deduction answer are `print`, a separate opt-in on the token.
    ("GET", f"{_SENDS}.list_print_sends"): "read",
    ("GET", f"{_SENDS}.get_print_send"): "read",
    ("POST", f"{_SENDS}.prepare_print_send"): "print",
    ("POST", f"{_SENDS}.confirm_print_send"): "print",
    ("POST", f"{_SENDS}.accept_print_consumption"): "print",
    ("POST", f"{_SENDS}.dismiss_print_consumption"): "print",
    # A token reading its own description (the MCP server's startup check)
    ("GET", f"{_TOKENS}.get_current_token"): ANY_SCOPE,
    # Generative AI (spec 008): reads are `read`; starting, cancelling, uploading an
    # input or adopting a result can spend money or change data, so `genai`.
    ("GET", f"{_GENAI}.list_capabilities"): "read",
    ("POST", f"{_GENAI}.estimate"): "read",
    ("GET", f"{_GENAI}.list_jobs"): "read",
    ("GET", f"{_GENAI}.get_job"): "read",
    ("GET", f"{_GENAI}.asset_file"): "read",
    ("POST", f"{_GENAI}.create_job"): "genai",
    ("POST", f"{_GENAI}.cancel_job"): "genai",
    ("POST", f"{_GENAI}.upload_input"): "genai",
    ("POST", f"{_GENAI}.adopt_asset"): "genai",
    # Preflight foundations (spec 009): reads `read`, writes `write`. Deleting a
    # design brief has no row: it stays for signed-in people only (FR-028).
    ("GET", f"{_BRIEFS}.get_idea_brief"): "read",
    ("POST", f"{_BRIEFS}.start_idea_brief"): "write",
    ("GET", f"{_BRIEFS}.get_model_brief"): "read",
    ("POST", f"{_BRIEFS}.start_model_brief"): "write",
    ("GET", f"{_BRIEFS}.get_brief"): "read",
    ("PATCH", f"{_BRIEFS}.update_brief"): "write",
    ("GET", f"{_BRIEFS}.list_brief_revisions"): "read",
    ("GET", f"{_CALIBRATIONS}.list_printer_calibrations"): "read",
    ("POST", f"{_CALIBRATIONS}.record_calibration"): "write",
    ("GET", f"{_CALIBRATIONS}.lookup_calibration"): "read",
    ("GET", f"{_CALIBRATIONS}.export_atelier_calibrations"): "read",
    ("GET", f"{_CALIBRATIONS}.get_calibration"): "read",
    ("POST", f"{_TESTS}.create_test_result"): "write",
    ("GET", f"{_TESTS}.list_test_results"): "read",
    ("GET", f"{_TESTS}.get_test_result"): "read",
    ("PATCH", f"{_TESTS}.update_test_result"): "write",
    ("POST", f"{_TESTS}.upload_test_result_photo"): "write",
    ("GET", f"{_TESTS}.get_test_result_photo"): "read",
}


def endpoint_key(endpoint: Callable[..., Any]) -> str:
    """`<module>.<qualname>` of a route handler."""
    return f"{endpoint.__module__}.{endpoint.__qualname__}"


def required_scope(method: str, endpoint: Optional[Callable[..., Any]]) -> Optional[TokenScope]:
    """The scope a token needs for this route, or None when tokens are refused there."""
    if endpoint is None:
        return None
    return TOKEN_ROUTE_SCOPES.get((method.upper(), endpoint_key(endpoint)))


def iter_routes(routes: list[Any]) -> Iterator[tuple[str, str, Callable[..., Any]]]:
    """Every `(method, full path, handler)` of an app, through lazily included routers."""
    for route in routes:
        kind = type(route).__name__
        if kind == "_IncludedRouter":
            yield from iter_routes(route.effective_candidates())
        elif kind == "_EffectiveRouteContext":
            methods = getattr(route.original_route, "methods", None) or set()
            if route.endpoint is not None:
                for method in sorted(methods):
                    yield method, route.path, route.endpoint
        elif getattr(route, "endpoint", None) is not None and getattr(route, "methods", None):
            for method in sorted(route.methods):
                yield method, route.path, route.endpoint
