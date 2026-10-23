"""Every field Kimai sends must reach the tool output, or be excused here.

PR #34 found one instance of a whole bug class: timesheet meta fields were
writable (``meta_update``) and parsed (``TimesheetEntity.meta_fields``), but no
action ever printed them, so for the model calling the tool they did not
exist. ``scripts/audit_api_models.py`` closes the gap between Kimai and the
models; this test closes the one between the models and the text a tool
returns.

It does so differentially rather than by searching for sentinel strings: for
every read surface (a tool action that renders records) and every field of the
model the client hands that surface, the record is rendered twice, once with
the field changed. Identical output means the field is invisible. That works
for booleans ("Yes"/"No"), nested objects and derived figures (seconds shown
as hours) alike, without knowing how a renderer formats a value.

A field that is deliberately not shown goes into ``NOT_RENDERED`` with the
reason. The excuses are checked too: an entry for a field that is in fact
rendered fails, so the list cannot rot.

``test_every_writable_field_is_readable`` covers the other half of the PR #34
symptom: what a tool can write must be readable through some ``get``.

Model fields are taken from the client method's return annotation, so a
surface checks exactly the model its data arrives in. Whether that model is the
right one for the endpoint is the audit script's job (``/users/me`` was parsed
as ``User`` and silently lost roles, teams and preferences).
"""

from __future__ import annotations

import re
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, get_args, get_origin
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from kimai_mcp import models
from kimai_mcp.client import KimaiClient, TimesheetPage
from kimai_mcp.tools import registry

_TZ = timezone(timedelta(hours=2))
_BASE_DT = datetime(2026, 3, 4, 9, 15, tzinfo=_TZ)

# Wire names of the list fields that are typed `list[dict]` in the models, so
# their shape is not derivable from the annotation.
_DICT_LISTS: dict[str, Callable[[int], list]] = {
    "metaFields": lambda v: [{"name": "ticket", "value": ("CA-376", "XY-999")[v]}],
    "preferences": lambda v: [{"name": "holidays", "value": ("30", "25")[v]}],
    "memberships": lambda v: [{"team": {"id": 5, "name": ("Team Alpha", "Team Omega")[v]}, "teamlead": v == 0}],
}


def _unwrap(annotation: Any) -> Any:
    """Strip Optional/Annotated; for a union of real types take the first."""
    origin = get_origin(annotation)
    if origin is typing.Annotated:
        return _unwrap(get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        return _unwrap(args[0])
    return annotation


def _value(annotation: Any, alias: str, variant: int, k: int) -> Any:
    """A wire value for one field; variant 0 and 1 always render differently.

    Numbers are far apart and whole hours, so a renderer that prints seconds as
    hours or minutes still shows two different figures.
    """
    if alias in _DICT_LISTS:
        return _DICT_LISTS[alias](variant)
    ann = _unwrap(annotation)
    origin = get_origin(ann)
    if origin is Literal:
        options = get_args(ann)
        return options[variant % len(options)]
    if origin is list:
        (item,) = get_args(ann)
        return [_value(item, alias, variant, k)]
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return _payload(ann, variant)
    if ann is bool:
        return variant == 0
    if ann is int:
        return 3600 * (k + 2) + variant * 30600
    if ann is float:
        return 10.5 + k + variant * 100.25
    if ann is datetime:
        return (_BASE_DT + timedelta(hours=k) - timedelta(days=100 * variant, hours=3 * variant)).isoformat()
    if ann is date:
        return (_BASE_DT.date() + timedelta(days=k) - timedelta(days=100 * variant)).isoformat()
    return f"{alias}-{k}{'az'[variant]}"


def _payload(model: type[BaseModel], variant: int = 0) -> dict:
    """Every field of ``model`` set, by wire name."""
    return {
        (info.alias or name): _value(info.annotation, info.alias or name, variant, k)
        for k, (name, info) in enumerate(model.model_fields.items())
    }


def _returned_model(method: str) -> type[BaseModel]:
    """The model a client method returns, unwrapped from list/tuple."""
    annotation = typing.get_type_hints(getattr(KimaiClient, method))["return"]
    while get_origin(annotation) in (list, tuple):
        annotation = get_args(annotation)[0]
    return _unwrap(annotation)


@dataclass
class Surface:
    """A tool action that renders records the client returns."""

    tool: str
    arguments: dict
    client_method: str
    many: bool = True  # the client returns a list of records
    # timesheet list returns (records, fetched_all, last_page)
    shape: Callable[[list], Any] | None = None
    # rendered text that legitimately changes between two renders
    volatile: str | None = None
    # the record model, where the client wraps the records (TimesheetPage)
    record_model: type[BaseModel] | None = None
    # tells two surfaces of the same action apart
    variant: str = ""

    @property
    def name(self) -> str:
        parts = [self.tool, self.arguments.get("action", "")]
        for key in ("type", "entity"):
            if key in self.arguments:
                parts.append(self.arguments[key])
        return " ".join(p for p in [*parts, self.variant] if p)

    @property
    def model(self) -> type[BaseModel]:
        return self.record_model or _returned_model(self.client_method)


SURFACES = [
    Surface("entity", {"type": "customer", "action": "list"}, "get_customers"),
    Surface("entity", {"type": "customer", "action": "get", "id": 1}, "get_customer", many=False),
    Surface("entity", {"type": "project", "action": "list"}, "get_projects"),
    Surface("entity", {"type": "project", "action": "get", "id": 1}, "get_project", many=False),
    Surface("entity", {"type": "activity", "action": "list"}, "get_activities"),
    Surface("entity", {"type": "activity", "action": "get", "id": 1}, "get_activity", many=False),
    Surface("entity", {"type": "user", "action": "list"}, "get_users"),
    Surface("entity", {"type": "user", "action": "get", "id": 1}, "get_user_extended", many=False),
    Surface("entity", {"type": "team", "action": "list"}, "get_teams"),
    Surface("entity", {"type": "team", "action": "get", "id": 1}, "get_team", many=False),
    Surface("entity", {"type": "tag", "action": "list"}, "get_tags_full"),
    Surface("entity", {"type": "invoice", "action": "list"}, "get_invoices"),
    Surface("entity", {"type": "invoice", "action": "get", "id": 1}, "get_invoice", many=False),
    Surface("entity", {"type": "holiday", "action": "list"}, "get_public_holidays"),
    # One page, Expanded (names) ...
    Surface("timesheet", {"action": "list", "filters": {"user_scope": "all"}}, "get_timesheet_page",
            record_model=models.TimesheetExpanded,
            shape=lambda rows: TimesheetPage(rows=rows, page=1, size=50, total=len(rows), total_pages=1)),
    # ... and everything, by ID, behind the statistics and the meta filter.
    Surface("timesheet", {"action": "list", "filters": {"user_scope": "all", "meta": {"name": "ticket"}}},
            "get_timesheets", shape=lambda rows: (rows, True, 1), variant="meta"),
    Surface("timesheet", {"action": "get", "id": 1}, "get_timesheet", many=False),
    Surface("timer", {"action": "active"}, "get_active_timesheets", volatile=r"running, [-\d.]+ h so far"),
    Surface("timer", {"action": "favorites"}, "get_favorite_timesheets"),
    Surface("timer", {"action": "recent"}, "get_recent_timesheets"),
    Surface("user_current", {}, "get_current_user", many=False),
    Surface("absence", {"action": "list", "filters": {"user_scope": "specific", "user": "1"}}, "get_absences"),
    Surface("comment", {"action": "list", "entity": "project", "entity_id": 1}, "get_comments"),
    Surface("rate", {"action": "list", "entity": "customer", "entity_id": 1}, "get_customer_rates"),
    Surface("rate", {"action": "list", "entity": "project", "entity_id": 1}, "get_project_rates"),
    Surface("rate", {"action": "list", "entity": "activity", "entity_id": 1}, "get_activity_rates"),
    Surface("calendar", {"type": "absences"}, "get_absences_calendar"),
    Surface("calendar", {"type": "holidays"}, "get_public_holidays_calendar"),
    Surface("config", {"type": "timesheet"}, "get_timesheet_config", many=False),
    Surface("config", {"type": "plugins"}, "get_plugins"),
    Surface("config", {"type": "version"}, "get_version", many=False),
]
SURFACES_BY_NAME = {s.name: s for s in SURFACES}


async def _render(surface: Surface, payload: dict) -> str:
    record = surface.model.model_validate(payload)
    returned: Any = [record] if surface.many else record
    if surface.shape:
        returned = surface.shape(returned)

    client = AsyncMock(spec=KimaiClient)
    client.get_current_user.return_value = models.UserEntity(id=1, username="me", enabled=True)
    getattr(client, surface.client_method).return_value = returned

    content = await registry.dispatch_tool(client, surface.tool, dict(surface.arguments))
    text = "\n".join(c.text for c in content)
    if surface.volatile:
        text = re.sub(surface.volatile, "", text)
    return text


_INVISIBLE: dict[str, set[str]] = {}


async def _invisible_fields(surface: Surface) -> set[str]:
    """Wire names whose value does not change the rendered text (cached per surface)."""
    if surface.name not in _INVISIBLE:
        _INVISIBLE[surface.name] = await _compute_invisible_fields(surface)
    return _INVISIBLE[surface.name]


async def _compute_invisible_fields(surface: Surface) -> set[str]:
    base = _payload(surface.model)
    other = _payload(surface.model, variant=1)
    rendered = await _render(surface, base)
    invisible = set()
    for alias in base:
        if base[alias] == other[alias]:
            continue  # a single-valued Literal cannot be varied
        changed = await _render(surface, {**base, alias: other[alias]})
        if changed == rendered:
            invisible.add(alias)
    return invisible


# Fields a surface deliberately does not show: surface name -> {wire name: why}.
_INITIALS = "derived by Kimai from the display name (User::getInitials), which is shown"
_TEAMS = "the same teams as `memberships`, which are shown because they also carry the team-lead flag"
_TEXT_COLOR = "a contrast colour Kimai derives from `color`, which is shown; display only"
_OWN = "these endpoints return the token's own records only, so every record has the caller as user"
NOT_RENDERED: dict[str, dict[str, str]] = {
    "timer active": {"user": _OWN},
    "timer favorites": {"user": _OWN},
    "timer recent": {"user": _OWN},
    "entity list user": {"initials": _INITIALS},
    "entity get user": {"initials": _INITIALS, "teams": _TEAMS},
    "user_current": {"initials": _INITIALS, "teams": _TEAMS},
    "calendar absences": {"textColor": _TEXT_COLOR},
    "calendar holidays": {"textColor": _TEXT_COLOR},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s.name)
async def test_every_field_is_rendered(surface):
    invisible = await _invisible_fields(surface)
    excused = NOT_RENDERED.get(surface.name, {})

    unexplained = sorted(invisible - excused.keys())
    assert not unexplained, (
        f"{surface.name}: {surface.model.__name__} fields that never reach the output: "
        f"{unexplained}. Render them, or add them to NOT_RENDERED with the reason."
    )
    stale = sorted(excused.keys() - invisible)
    assert not stale, f"{surface.name}: NOT_RENDERED lists fields that are rendered after all: {stale}"


# Client getters whose records no tool renders as such.
NO_SURFACE = {
    "get_api_tokens": "used by automatic provisioning only, never shown to a tool caller",
}


def test_every_client_getter_has_a_surface():
    """A new getter (or a new model behind one) cannot escape the check above."""
    covered = {s.client_method for s in SURFACES}
    missing = []
    for name in dir(KimaiClient):
        if not name.startswith("get_") or name in covered or name in NO_SURFACE:
            continue
        model = _returned_model(name)
        if isinstance(model, type) and issubclass(model, BaseModel):
            missing.append(name)
    assert not missing, f"client getters returning models with no Surface in this test: {missing}"
    assert not (covered & NO_SURFACE.keys()), "a getter is both covered and excused"


# --- write -> read ----------------------------------------------------------

# Write models -> the surface that shows the written record again.
WRITE_FORMS = {
    models.CustomerEditForm: "entity get customer",
    models.ProjectEditForm: "entity get project",
    models.ActivityEditForm: "entity get activity",
    models.TimesheetEditForm: "timesheet get",
    models.UserCreateForm: "entity get user",
    models.UserEditForm: "entity get user",
    models.TeamEditForm: "entity get team",
    models.TagEditForm: "entity list tag",
    models.InvoiceEditForm: "entity get invoice",
    models.RateForm: "rate list customer",
    models.CommentForm: "comment list project",
    models.AbsenceForm: "absence list",
}

# A form field that comes back under another wire name.
READ_BACK_AS = {(models.AbsenceForm, "end"): "endDate"}

# Writable fields Kimai never sends back, so no tool can show them.
WRITE_ONLY = {
    (models.CustomerEditForm, "invoiceText"): "no serializer group on Customer::$invoiceText",
    (models.CustomerEditForm, "invoiceTemplate"): "no serializer group on Customer::$invoiceTemplate",
    (models.ProjectEditForm, "invoiceText"): "no serializer group on Project::$invoiceText",
    (models.ActivityEditForm, "invoiceText"): "no serializer group on Activity::$invoiceText",
    (models.UserCreateForm, "plainPassword"): "a password is never sent back",
    (models.UserCreateForm, "plainApiToken"): "a token is never sent back",
    (models.UserCreateForm, "requiresPasswordReset"): "stored as an internal preference Kimai hides",
    (models.UserEditForm, "requiresPasswordReset"): "stored as an internal preference Kimai hides",
}


def _write_actions() -> list[tuple[str, str, str]]:
    """Writes that are an action rather than a form field: (what, surface, read-back field).

    Derived from the tool schemas where possible, so a new meta entity or a new
    team_access target is checked without touching this test.
    """
    from kimai_mcp.tools.calendar_meta import meta_tool
    from kimai_mcp.tools.team_access_manager import team_access_tool

    get_surface = {
        "customer": "entity get customer",
        "project": "entity get project",
        "activity": "entity get activity",
        "invoice": "entity get invoice",
        "timesheet": "timesheet get",
    }
    actions = [
        (f"meta update {entity}", get_surface[entity], "metaFields")
        for entity in meta_tool().input_schema["properties"]["entity"]["enum"]
    ]
    actions += [
        (f"team_access grant/revoke {target}", "entity get team", f"{'activities' if target == 'activity' else target + 's'}")
        for target in team_access_tool().input_schema["properties"]["target"]["enum"]
    ]
    actions += [
        ("team_access add_member/remove_member", "entity get team", "members"),
        ("timesheet meta_update", "timesheet get", "metaFields"),
        ("timesheet export_toggle", "timesheet get", "exported"),
        ("entity set_preferences", "entity get user", "preferences"),
        ("comment pin", "comment list project", "pinned"),
        ("absence approve/reject/request", "absence list", "status"),
    ]
    return actions


def _write_checks() -> list[tuple[str, str, str]]:
    checks = []
    for form, surface in WRITE_FORMS.items():
        for name, info in form.model_fields.items():
            alias = info.alias or name
            if (form, alias) in WRITE_ONLY:
                continue
            checks.append((f"{form.__name__}.{alias}", surface, READ_BACK_AS.get((form, alias), alias)))
    return checks + _write_actions()


@pytest.mark.asyncio
@pytest.mark.parametrize(("written", "surface_name", "read_as"), _write_checks(), ids=lambda v: str(v))
async def test_every_writable_field_is_readable(written, surface_name, read_as):
    surface = SURFACES_BY_NAME[surface_name]
    model_fields = {info.alias or name for name, info in surface.model.model_fields.items()}
    assert read_as in model_fields, (
        f"{written} can be written, but {surface.model.__name__} (read by '{surface_name}') "
        f"has no field '{read_as}'. Model it, or list it in WRITE_ONLY with the reason."
    )
    assert read_as not in await _invisible_fields(surface), (
        f"{written} can be written, but '{surface_name}' never shows '{read_as}'"
    )


def test_write_only_excuses_name_real_fields():
    for form, alias in WRITE_ONLY:
        assert alias in {info.alias or n for n, info in form.model_fields.items()}, (form, alias)
