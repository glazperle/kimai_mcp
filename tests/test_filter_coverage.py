"""Every filter the client can send must be reachable from a tool, or be excused here.

The second half of PR #34: Kimai filters timesheets by meta field server-side
(the ``name:value`` search term), but no tool argument could ask for it.
``scripts/audit_api_models.py`` compares Kimai's query parameters with what the
*client* can send; this test checks the remaining hop, tool argument -> client
call, offline.

For each list surface, every field of the filter the client method takes (or
every keyword of a method without a filter model) is probed differentially:
the tool is called once without and once with the filter that should set it,
and the value the client receives must change. A field no tool argument
reaches goes into ``NOT_EXPOSED`` with the reason.

It also pins the schema enums to the client's Literal types, so a tool cannot
advertise a value Kimai rejects: ``order_by`` for projects used to list eleven
sort fields, of which Kimai's API accepts three.
"""

from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass, field
from typing import Any, get_args, get_origin
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from kimai_mcp import models
from kimai_mcp.client import KimaiClient
from kimai_mcp.tools import registry

_DATETIME = "2026-01-02T03:04:05"


@dataclass
class ListSurface:
    tool: str
    arguments: dict
    client_method: str
    returns: Any = field(default_factory=list)
    # client field -> the tool filters that should set it, where not {field: probe}
    probes: dict[str, dict] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return " ".join(str(v) for v in (self.tool, self.arguments.get("type", ""), "list") if v)


LIST_SURFACES = [
    ListSurface(
        "timesheet", {"action": "list"}, "get_timesheets", returns=([], True, 1),
        probes={
            "user": {"user_scope": "all"},
            "begin": {"begin": _DATETIME},
            "end": {"end": _DATETIME},
            "modified_after": {"modified_after": _DATETIME},
        },
    ),
    ListSurface(
        "entity", {"type": "project", "action": "list"}, "get_projects",
        probes={"start": {"begin": _DATETIME}, "end": {"end": _DATETIME}, "order_by": {"order_by": "customer"}},
    ),
    ListSurface("entity", {"type": "activity", "action": "list"}, "get_activities",
                probes={"order_by": {"order_by": "project"}}),
    ListSurface("entity", {"type": "customer", "action": "list"}, "get_customers",
                probes={"order_by": {"order_by": "id"}}),
    ListSurface("entity", {"type": "user", "action": "list"}, "get_users",
                probes={"order_by": {"order_by": "email"}}),
    ListSurface("entity", {"type": "tag", "action": "list"}, "get_tags_full"),
    ListSurface(
        "entity", {"type": "invoice", "action": "list"}, "get_invoices",
        probes={"begin": {"begin": _DATETIME}, "end": {"end": _DATETIME}},
    ),
    ListSurface(
        "entity", {"type": "holiday", "action": "list"}, "get_public_holidays",
        probes={"begin": {"begin": _DATETIME}, "end": {"end": _DATETIME}},
    ),
    ListSurface(
        "absence", {"action": "list"}, "get_absences",
        probes={
            "user": {"user_scope": "specific", "user": "5"},
            "begin": {"begin": "2026-01-02"},
            "end": {"end": "2026-01-02"},
            "status": {"status": "approved"},  # the tool's default is "all"
        },
    ),
]

# Client-side filter fields no tool argument sets: surface -> {field: why}.
NOT_EXPOSED: dict[str, dict[str, str]] = {
    "timesheet list": {
        "full": "switches the listing to the Expanded schema (objects for ids); the client parses TimesheetEntity",
    },
    "entity user list": {
        "full": "adds the UserEntity fields, but the listing is parsed as User; entity get shows them",
    },
}


def _filter_schema(tool: str) -> dict:
    tool_def = next(t for t in registry.all_tools() if t.name == tool)
    return tool_def.input_schema["properties"]["filters"]["properties"]


def _probe(prop: dict) -> Any:
    """A value for a schema property that differs from what omitting it does."""
    if "enum" in prop:
        return prop["enum"][-1]
    kind = prop.get("type")
    if kind == "array":
        item = prop.get("items", {})
        if "enum" in item:
            return [item["enum"][-1]]
        return [7, 8] if item.get("type") == "integer" else ["probe"]
    if kind == "integer":
        return 7
    if kind == "boolean":
        return True
    return _DATETIME if prop.get("format") == "date-time" else "probe"


def _client_fields(method: str) -> dict[str, tuple[str, str | None]]:
    """field -> (parameter, filter field or None) for one client method."""
    hints = typing.get_type_hints(getattr(KimaiClient, method))
    fields: dict[str, tuple[str, str | None]] = {}
    for param in inspect.signature(getattr(KimaiClient, method)).parameters:
        if param == "self":
            continue
        annotation = hints.get(param)
        candidates = [annotation, *get_args(annotation)]
        model = next((c for c in candidates if isinstance(c, type) and issubclass(c, BaseModel)), None)
        if model is not None:
            for name in model.model_fields:
                fields[name] = (param, name)
        else:
            fields[param] = (param, None)
    return fields


async def _sent(surface: ListSurface, filters: dict) -> dict[str, Any]:
    """What the client method received, per client field."""
    client = AsyncMock(spec=KimaiClient)
    client.get_current_user.return_value = models.UserEntity(id=1, username="me", enabled=True)
    method = getattr(client, surface.client_method)
    method.return_value = surface.returns

    arguments = {**surface.arguments, "filters": filters}
    await registry.dispatch_tool(client, surface.tool, arguments)

    bound = inspect.signature(getattr(KimaiClient, surface.client_method)).bind(
        None, *method.await_args.args, **method.await_args.kwargs
    )
    bound.apply_defaults()
    sent = {}
    for name, (param, attr) in _client_fields(surface.client_method).items():
        value = bound.arguments.get(param)
        sent[name] = getattr(value, attr, None) if attr else value
    return sent


def _cases():
    for surface in LIST_SURFACES:
        for name in _client_fields(surface.client_method):
            yield pytest.param(surface, name, id=f"{surface.name}: {name}")


@pytest.mark.asyncio
@pytest.mark.parametrize(("surface", "client_field"), list(_cases()))
async def test_every_client_filter_is_reachable(surface, client_field):
    if surface.client_method == "get_timesheets" and client_field == "max_results":
        pytest.skip("client-side cap on auto-pagination, not a Kimai parameter")
    excused = NOT_EXPOSED.get(surface.name, {})
    schema = _filter_schema(surface.tool)

    probe = surface.probes.get(client_field)
    if probe is None:
        if client_field not in schema:
            assert client_field in excused, (
                f"{surface.name}: the client can send '{client_field}', but the tool's filters "
                "have no such key. Expose it, or add it to NOT_EXPOSED with the reason."
            )
            return
        probe = {client_field: _probe(schema[client_field])}

    base = await _sent(surface, {})
    probed = await _sent(surface, probe)
    reached = base[client_field] != probed[client_field]
    if client_field in excused:
        assert not reached, f"{surface.name}: '{client_field}' is excused in NOT_EXPOSED but reachable"
        return
    assert reached, f"{surface.name}: filters {probe} never reach the client's '{client_field}'"


def test_not_exposed_names_real_fields():
    surfaces = {s.name: s for s in LIST_SURFACES}
    for name, excused in NOT_EXPOSED.items():
        assert excused.keys() <= _client_fields(surfaces[name].client_method).keys(), name


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_type", ["project", "activity", "customer", "user", "team", "tag", "invoice", "holiday"])
async def test_entity_filters_that_do_not_apply_are_reported(entity_type):
    """The filters object is shared by all types; a key a type ignores must be named."""
    from kimai_mcp.tools.entity_manager import handle_entity

    schema = _filter_schema("entity")
    client = AsyncMock(spec=KimaiClient)
    for method in ("get_projects", "get_activities", "get_customers", "get_users", "get_teams",
                   "get_tags_full", "get_invoices", "get_public_holidays"):
        getattr(client, method).return_value = []

    for key, prop in schema.items():
        value = ORDER_BY_PROBE.get(entity_type, "id") if key == "order_by" else _probe(prop)
        content = await handle_entity(client, type=entity_type, action="list", filters={key: value})
        note = content[-1].text if len(content) > 1 else ""
        handler_keys = _list_filters(entity_type)
        if key in handler_keys:
            assert "ignored" not in note, f"type={entity_type}: '{key}' is applied but reported as ignored"
        else:
            assert key in note, f"type={entity_type}: filter '{key}' is silently ignored"


# A sort field each type's API accepts (order_by is a strict per-type list).
ORDER_BY_PROBE = {"project": "customer", "activity": "project", "customer": "name", "user": "email"}


def _list_filters(entity_type: str) -> frozenset:
    from kimai_mcp.tools import entity_manager

    handler = {
        "project": entity_manager.ProjectEntityHandler,
        "activity": entity_manager.ActivityEntityHandler,
        "customer": entity_manager.CustomerEntityHandler,
        "user": entity_manager.UserEntityHandler,
        "team": entity_manager.TeamEntityHandler,
        "tag": entity_manager.TagEntityHandler,
        "invoice": entity_manager.InvoiceEntityHandler,
        "holiday": entity_manager.HolidayEntityHandler,
    }[entity_type]
    return handler.list_filters


def _literal_args(annotation) -> tuple:
    """The values of the first Literal inside an annotation, in declaration order."""
    if get_origin(annotation) is typing.Literal:
        return get_args(annotation)
    for arg in get_args(annotation):
        if inner := _literal_args(arg):
            return inner
    return ()


@pytest.mark.parametrize(("tool", "key", "model", "field_name"), [
    ("timesheet", "order_by", models.TimesheetFilter, "order_by"),
    ("timesheet", "order", models.TimesheetFilter, "order"),
    ("entity", "order", models.ProjectFilter, "order"),
    ("entity", "status", models.InvoiceFilter, "status"),
])
def test_schema_enums_match_the_client_literals(tool, key, model, field_name):
    prop = _filter_schema(tool)[key]
    enum = prop.get("enum") or prop.get("items", {}).get("enum")
    assert set(enum) == set(_literal_args(model.model_fields[field_name].annotation))


def test_entity_order_by_lists_exactly_the_api_sort_fields():
    """The shared order_by is free text; its description is the only guidance."""
    description = _filter_schema("entity")["order_by"]["description"]
    for entity_type, model in (("project", models.ProjectFilter), ("activity", models.ActivityFilter),
                               ("customer", models.CustomerFilter), ("user", models.UserFilter)):
        values = _literal_args(model.model_fields["order_by"].annotation)
        assert f"{entity_type}: {', '.join(values)}" in description
