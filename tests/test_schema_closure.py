"""Tool input schemas are closed, and every key a handler reads is declared.

SDK 2.x does not validate arguments server-side; tools/registry.py does, and
since the registry closes every object schema (``additionalProperties:
false``), a misspelt key (``filters.projet``, ``data.emial``) is an input
validation error instead of a parameter that is silently ignored while the
call reports success.

Closing has a converse risk: a key a handler reads but the schema does not
declare becomes unreachable. The second test reads the handler sources and
fails on such a key (the tag filter ``name`` was one, until it was declared).
"""

from __future__ import annotations

import ast
import inspect
from collections import defaultdict

import pytest

from kimai_mcp import models
from kimai_mcp.tools import entity_manager, registry

# Names under which handlers hold tool input.
INPUT_NAMES = {"params", "filters", "data", "arguments", "meta_filter"}


def _objects(schema, path=""):
    """(path, object schema) for every object reachable through properties/items."""
    if not isinstance(schema, dict):
        return
    if "properties" in schema:
        yield path or "/", schema
    for key, sub in schema.get("properties", {}).items():
        yield from _objects(sub, f"{path}/{key}")
    if isinstance(schema.get("items"), dict):
        yield from _objects(schema["items"], f"{path}[]")
    for i, sub in enumerate(schema.get("anyOf", [])):
        yield from _objects(sub, f"{path}/anyOf[{i}]")


@pytest.mark.parametrize("tool", registry.all_tools(), ids=lambda t: t.name)
def test_every_input_object_is_closed(tool):
    open_objects = [path for path, obj in _objects(tool.input_schema) if obj.get("additionalProperties") is not False]
    assert not open_objects, f"{tool.name}: open object schemas {open_objects}"


@pytest.mark.parametrize("name", registry.tool_names())
def test_clients_are_shown_the_schema_the_server_validates(name):
    """One schema: what a client checks locally is what the server checks,
    plus the tool's own check (registry._CHECKS) for what a schema without a
    root combinator cannot say (issue #38)."""
    shown = next(t for t in registry.all_tools() if t.name == name).input_schema
    assert shown == registry._closed_schema(name)


def test_misspelt_filter_is_rejected():
    tool = next(t for t in registry.all_tools() if t.name == "timesheet")
    with pytest.raises(registry.ToolError, match="projet"):
        registry.validate_arguments(tool, {"action": "list", "filters": {"projet": 3}})


def _handler_modules() -> dict:
    modules = defaultdict(list)
    for tool in registry.all_tools():
        factory = registry._REGISTRY[tool.name][0]
        modules[inspect.getmodule(factory)].append(tool)
    return modules


@pytest.mark.parametrize(
    ("module", "tools"), list(_handler_modules().items()), ids=lambda v: getattr(v, "__name__", "")
)
def test_every_key_a_handler_reads_is_declared(module, tools):
    """Per variable, against the object it holds: a key read as ``filters.X``
    must be declared under ``filters``, not just anywhere in the schema."""
    schemas = [registry._closed_schema(t.name) for t in tools]
    declared = {var: set().union(*(_declared_at(s, var) for s in schemas)) for var in INPUT_NAMES}
    undeclared: dict[str, int] = {}
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        var = key = None
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name) and node.func.value.id in INPUT_NAMES
                and node.args and isinstance(node.args[0], ast.Constant)):
            var, key = node.func.value.id, node.args[0].value
        elif (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
              and node.value.id in INPUT_NAMES and isinstance(node.slice, ast.Constant)):
            var, key = node.value.id, node.slice.value
        if isinstance(key, str) and key not in declared[var]:
            undeclared.setdefault(f"{var}.{key}", node.lineno)
    assert not undeclared, f"{module.__name__} reads keys its schema does not declare there (key: line): {undeclared}"


def _declared_at(schema: dict, var: str) -> set[str]:
    """Property names of the object a handler variable holds."""
    root = schema.get("properties", {})
    if var in ("params", "arguments"):
        return set(root)
    if var == "filters":
        return set(root.get("filters", {}).get("properties", {}))
    if var == "meta_filter":
        return set(root.get("filters", {}).get("properties", {}).get("meta", {}).get("properties", {}))
    # data: the object itself and every alternative of the entity data
    data = root.get("data", {})
    names = set(data.get("properties", {}))
    for option in data.get("anyOf", []):
        names |= set(option.get("properties", {}))
    return names


def test_key_check_sees_a_key_declared_only_elsewhere():
    """The case the union over all property names missed: `name` exists in many
    data branches, so deleting it from filters went unnoticed."""
    schema = registry._closed_schema("entity")
    assert "name" in _declared_at(schema, "filters")
    assert "name" in _declared_at(schema, "data")
    assert "ignore_dates" not in _declared_at(schema, "data")


# --- write schemas vs. request models ---------------------------------------


# Write schemas that deliberately take a subset of their request model.
SUBSET_BY_DESIGN = {
    ("timer", None): "timer start takes project, activity, description and tags; "
                     "everything else is the timesheet tool's",
}

WRITE_SCHEMAS = [
    ("entity", ("customer", "create"), models.CustomerEditForm),
    ("entity", ("customer", "update"), models.CustomerEditForm),
    ("entity", ("project", "create"), models.ProjectEditForm),
    ("entity", ("project", "update"), models.ProjectEditForm),
    ("entity", ("activity", "create"), models.ActivityEditForm),
    ("entity", ("activity", "update"), models.ActivityEditForm),
    ("entity", ("user", "create"), models.UserCreateForm),
    ("entity", ("user", "update"), models.UserEditForm),
    ("entity", ("team", "create"), models.TeamEditForm),
    ("entity", ("team", "update"), models.TeamEditForm),
    ("entity", ("tag", "create"), models.TagEditForm),
    ("entity", ("invoice", "update"), models.InvoiceEditForm),
    ("timesheet", None, models.TimesheetEditForm),
    ("absence", None, models.AbsenceForm),
    ("comment", None, models.CommentForm),
    ("rate", None, models.RateForm),
    ("timer", None, models.TimesheetEditForm),
]


def _tool(name):
    return next(t for t in registry.all_tools() if t.name == name)


def _entity_data(entity: str, action: str) -> dict | None:
    """The alternative of the entity data a type and action select, by position."""
    options = _tool("entity").input_schema["properties"]["data"]["anyOf"]
    for option, (slot_type, actions) in zip(options, entity_manager.data_slots(), strict=True):
        if slot_type == entity and action in actions:
            return option
    return None


@pytest.mark.parametrize(("tool", "where", "form"), WRITE_SCHEMAS, ids=lambda v: getattr(v, "__name__", str(v)))
def test_write_schema_matches_its_request_model(tool, where, form):
    """A closed data schema lacking a model field makes that field unwritable;
    one listing a field the model lacks lets Pydantic drop it silently."""
    data = _entity_data(*where) if where else _tool(tool).input_schema["properties"]["data"]
    assert data is not None, f"{tool} {where}: no data schema"
    declared = set(data["properties"])
    # A schema key may use the wire name or the Python name (the rate handler
    # maps internal_rate itself); either way it must be one field of the model.
    names = {name: {name, info.alias or name} for name, info in form.model_fields.items()}
    unknown = sorted(k for k in declared if not any(k in spellings for spellings in names.values()))
    missing = sorted(n for n, spellings in names.items() if not spellings & declared)
    assert not unknown, f"{tool} {where}: schema keys the model does not have: {unknown}"
    if (tool, where) in SUBSET_BY_DESIGN:
        return
    assert not missing, f"{tool} {where}: model fields the schema cannot send: {missing}"


def test_every_entity_write_has_one_data_schema_or_a_reason():
    """Each write either has exactly one closed alternative in `data`, or is
    refused with the reason in UNSUPPORTED_WRITES; nothing falls in between."""
    slots = entity_manager.data_slots()
    assert len(slots) == len(_tool("entity").input_schema["properties"]["data"]["anyOf"])
    for entity in entity_manager.ENTITY_TYPES:
        for action in entity_manager.WRITE_ACTIONS:
            schemas = [s for s, (t, actions) in enumerate(slots) if t == entity and action in actions]
            if (entity, action) in entity_manager.UNSUPPORTED_WRITES:
                assert not schemas, f"{entity} {action}: refused, yet has a data schema"
                continue
            assert len(schemas) == 1, f"{entity} {action}: {len(schemas)} data schemas"
            assert _entity_data(entity, action)["additionalProperties"] is False, (entity, action)
    assert {t for t, _ in slots} <= set(entity_manager.ENTITY_TYPES)
    assert {a for _, actions in slots for a in actions} <= set(entity_manager.WRITE_ACTIONS)


# --- what the schema cannot say (entity_manager.check_entity_call) -----------


def test_data_is_held_to_its_type():
    """`country` is a customer field: the schema's alternatives take it on a
    project, the tool's own check must not, and must name the field."""
    call = {"type": "project", "action": "create", "data": {"name": "P", "country": "DE"}}
    registry.validate_arguments(_tool("entity"), call)
    with pytest.raises(registry.ToolError, match=r"at 'data': .*'country' was unexpected"):
        registry.validate_call("entity", call)


def test_a_typo_in_data_is_named_against_its_type():
    """Not as 'is not valid under any of the given schemas'."""
    with pytest.raises(registry.ToolError, match=r"at 'data/members/0': .*'lead' was unexpected"):
        registry.validate_call("entity", {"type": "team", "action": "create",
                                          "data": {"name": "T", "members": [{"user": 1, "lead": True}]}})


@pytest.mark.parametrize("action", ["list", "get", "delete", "batch_delete"])
def test_data_is_refused_where_no_write_happens(action):
    with pytest.raises(registry.ToolError, match=f"action={action} takes no data"):
        registry.validate_call("entity", {"type": "project", "action": action, "id": 1, "data": {}})


@pytest.mark.parametrize(("entity", "action"), sorted(entity_manager.UNSUPPORTED_WRITES))
def test_an_unsupported_write_gets_its_reason(entity, action):
    """Holiday data fits none of the alternatives; the caller learns why the
    write is not possible, not that the data has the wrong shape."""
    with pytest.raises(registry.ToolError, match=entity_manager.UNSUPPORTED_WRITES[(entity, action)]):
        registry.validate_call("entity", {"type": entity, "action": action, "id": 1,
                                          "data": {"name": "X", "date": "2026-12-24"}})


def test_an_unknown_type_or_action_is_left_to_the_schema():
    with pytest.raises(registry.ToolError, match="at 'action'"):
        registry.validate_call("entity", {"type": "project", "action": "craete", "data": {"name": "P"}})
    with pytest.raises(registry.ToolError, match="at 'type'"):
        registry.validate_call("entity", {"type": "projekt", "action": "list"})


def test_the_tool_schemas_stay_within_their_token_budget():
    """Every word of the tool schemas is sent with every request, before the
    caller has asked anything. They were 41k characters (about 10k tokens),
    half of it the entity tool repeating the same budget explanation three
    times. Raise the limit only for a field that needs the words."""
    import json

    size = sum(
        len(json.dumps(tool.model_dump(by_alias=True, exclude_none=True), separators=(",", ":")))
        for tool in registry.all_tools()
    )
    assert size <= 32_000, f"tool schemas are {size} characters (about {size // 4} tokens)"
