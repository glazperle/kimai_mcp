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
from kimai_mcp.tools import registry

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
    # if/then/else/allOf branches are deliberately not closed: a closed `if`
    # would stop matching, a closed `then` would reject every other key.
    for branch in schema.get("allOf", []):
        for part in ("then", "else"):
            for key, sub in branch.get(part, {}).get("properties", {}).items():
                yield from _objects(sub, f"{path}/allOf/{part}/{key}")



@pytest.mark.parametrize("tool", registry.all_tools(), ids=lambda t: t.name)
def test_every_input_object_is_closed(tool):
    open_objects = [
        path for path, obj in _objects(tool.input_schema)
        if obj.get("additionalProperties") is not False and path not in OPEN_BY_DESIGN.get(tool.name, {})
    ]
    assert not open_objects, f"{tool.name}: open object schemas {open_objects}"


# Objects that stay open, with the reason.
OPEN_BY_DESIGN = {
    "entity": {
        "/data": "closed per type by the allOf branches; one shared object cannot list every type's fields",
    },
}


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
    declared = {var: set().union(*(_declared_at(t.input_schema, var) for t in tools)) for var in INPUT_NAMES}
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
    # data: the shared object and every per-type branch
    names = set(root.get("data", {}).get("properties", {}))
    for branch in schema.get("allOf", []):
        names |= set(branch.get("then", {}).get("properties", {}).get("data", {}).get("properties", {}))
    return names


def test_key_check_sees_a_key_declared_only_elsewhere():
    """The case the union over all property names missed: `name` exists in many
    data branches, so deleting it from filters went unnoticed."""
    schema = next(t for t in registry.all_tools() if t.name == "entity").input_schema
    assert "name" in _declared_at(schema, "filters")
    assert "name" in _declared_at(schema, "data")
    assert "ignore_dates" not in _declared_at(schema, "data")


# --- write schemas vs. request models ---------------------------------------


# Entity writes the handler refuses outright, so no data schema is needed.
UNSUPPORTED_WRITES = {("invoice", "create"), ("holiday", "create"), ("holiday", "update"), ("tag", "update")}

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
    for branch in _tool("entity").input_schema["allOf"]:
        given = branch.get("if", {}).get("properties", {})
        if given.get("type", {}).get("const") == entity and action in given.get("action", {}).get("enum", []):
            data = branch.get("then", {}).get("properties", {}).get("data")
            if data is not None:
                return data
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


def test_every_supported_entity_write_has_a_closed_data_schema():
    types = _tool("entity").input_schema["properties"]["type"]["enum"]
    for entity in types:
        for action in ("create", "update"):
            if (entity, action) in UNSUPPORTED_WRITES:
                continue
            data = _entity_data(entity, action)
            assert data is not None, (entity, action)
            assert data.get("additionalProperties") is False, (entity, action)


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
