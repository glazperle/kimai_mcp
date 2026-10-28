"""Shared tool registry consumed by both the stdio and streamable HTTP servers.

Having a single source of truth for the tool list and the name->handler dispatch
prevents the two servers from drifting apart (e.g. a tool registered in one but
not the other).
"""
import functools
import json
from typing import Any

import jsonschema
import pydantic
from mcp.types import TextContent, Tool

from .. import models
from ..client import KimaiClient
from .absence_manager import absence_tool, handle_absence
from .calendar_meta import (
    calendar_tool,
    handle_calendar,
    handle_meta,
    handle_user_current,
    meta_tool,
    user_current_tool,
)
from .comment_tool import comment_tool, handle_comment
from .config_info import config_tool, handle_config
from .entity_manager import entity_tool, handle_entity
from .errors import ToolError
from .project_analysis import analyze_project_team_tool, handle_analyze_project_team
from .rate_manager import handle_rate, rate_tool
from .team_access_manager import handle_team_access, team_access_tool
from .timesheet_consolidated import (
    handle_timer,
    handle_timesheet,
    timer_tool,
    timesheet_tool,
)


def _kw(handler):
    """Adapter for handlers called as handler(client, **arguments)."""
    async def _run(client, arguments):
        return await handler(client, **arguments)
    return _run


def _positional(handler):
    """Adapter for handlers called as handler(client, arguments)."""
    async def _run(client, arguments):
        return await handler(client, arguments)
    return _run


# Ordered name -> (tool factory, dispatch adapter). Insertion order defines the
# order in which tools are advertised to the MCP client.
_REGISTRY = {
    "entity": (entity_tool, _kw(handle_entity)),
    "timesheet": (timesheet_tool, _kw(handle_timesheet)),
    "timer": (timer_tool, _kw(handle_timer)),
    "rate": (rate_tool, _kw(handle_rate)),
    "team_access": (team_access_tool, _kw(handle_team_access)),
    "absence": (absence_tool, _kw(handle_absence)),
    "calendar": (calendar_tool, _kw(handle_calendar)),
    "meta": (meta_tool, _kw(handle_meta)),
    "user_current": (user_current_tool, _kw(handle_user_current)),
    "analyze_project_team": (analyze_project_team_tool, _positional(handle_analyze_project_team)),
    "config": (config_tool, _kw(handle_config)),
    "comment": (comment_tool, _kw(handle_comment)),
}


def _close(schema: dict) -> None:
    """Set ``additionalProperties: false`` on every input object, in place.

    Reaches the root, everything below ``properties`` and ``items``, and the
    objects a conditional branch declares under its ``properties``, but never
    an ``if``/``then``/``else`` schema itself: a closed ``if`` would stop
    matching, a closed ``then`` would reject every key it does not repeat.
    An explicit ``additionalProperties`` (the entity ``data`` object, closed
    per type by its branches) is left as it is.
    """
    if "properties" in schema:
        schema.setdefault("additionalProperties", False)
        for sub in schema["properties"].values():
            if isinstance(sub, dict):
                _close(sub)
    if isinstance(schema.get("items"), dict):
        _close(schema["items"])
    for branch in schema.get("allOf", []):
        for part in ("then", "else"):
            for sub in branch.get(part, {}).get("properties", {}).values():
                if isinstance(sub, dict):
                    _close(sub)


def _build(factory) -> Tool:
    """A tool definition as validated: every input object closed.

    SDK 2.x validates nothing server-side, and the Pydantic forms ignore
    unknown keys, so an open object turns a misspelt key into a silently
    ignored one while the call reports success. Closing them centrally covers
    every tool, including the next one.
    """
    tool = factory()
    _close(tool.input_schema)
    return tool


def _for_clients(schema: dict) -> dict:
    """``schema`` as advertised: a plain object, no combinator at its root.

    The Anthropic API refuses an ``input_schema`` with ``allOf``, ``anyOf`` or
    ``oneOf`` at the top level; Claude clients drop such a tool, others fail
    the whole request (issue #38). The entity tool needs its root ``allOf``,
    because only the root sees ``type`` and ``action`` next to ``data``.
    Clients get each branch's schema of a property as one alternative of an
    ``anyOf`` on that property, labelled with the branch's condition. The
    rules without a schema of their own (``id`` required, ``data`` required
    on a write and refused otherwise) are in the property descriptions;
    ``tests/test_schema_closure.py`` holds every such rule to that. Validation
    keeps the full schema (``validate_call``).
    """
    branches = schema.get("allOf")
    if not branches:
        return schema
    properties = dict(schema["properties"])
    alternatives: dict[str, list[dict]] = {}
    for branch in branches:
        condition = ", ".join(
            f"{key}={'|'.join(map(str, sub['enum'])) if 'enum' in sub else sub.get('const')}"
            for key, sub in branch.get("if", {}).get("properties", {}).items()
        )
        for key, sub in branch.get("then", {}).get("properties", {}).items():
            label = f"{condition}: {sub['description']}" if sub.get("description") else condition
            alternatives.setdefault(key, []).append({**sub, "description": label})
    for key, options in alternatives.items():
        shared = {k: v for k, v in properties.get(key, {}).items() if k != "additionalProperties"}
        properties[key] = {**shared, "anyOf": options}
    return {**{k: v for k, v in schema.items() if k != "allOf"}, "properties": properties}


def all_tools() -> list[Tool]:
    """Return the Tool definitions as advertised to clients, in order."""
    tools = []
    for factory, _ in _REGISTRY.values():
        tool = _build(factory)
        tools.append(tool.model_copy(update={"input_schema": _for_clients(tool.input_schema)}))
    return tools


def tool_names() -> list[str]:
    """Return the registered tool names."""
    return list(_REGISTRY.keys())


@functools.lru_cache(maxsize=64)
def _validator(schema_json: str) -> Any:
    """A checked validator per distinct schema (keyed by its JSON text)."""
    schema = json.loads(schema_json)
    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    return validator_class(schema)


def validate_arguments(tool: Tool, arguments: dict[str, Any]) -> None:
    """Validate tool arguments against the tool's own JSON schema.

    MCP SDK 1.x validated this server-side before calling the handler and
    answered ``Input validation error: ...``; SDK 2.x dropped that entirely
    (jsonschema is only used client-side now). Without it, a typo in a nested
    object silently passes: the entity schemas are ``additionalProperties:
    false`` while the Pydantic forms ignore extras, so ``{"langauge": "de"}``
    would produce an empty PATCH and still report success.

    A tool from ``all_tools()`` carries the form clients are shown, which is
    looser for the entity tool; ``validate_call`` is the server's check.

    Raises:
        ToolError: if the arguments do not satisfy the schema.
    """
    # jsonschema.validate() checks the schema itself against the meta-schema
    # on every call, ~70 ms for the entity schema; a cached validator ~0.2 ms.
    _check(_validator(json.dumps(tool.input_schema, sort_keys=True)), arguments)


def validate_call(name: str, arguments: dict[str, Any]) -> None:
    """The check ``dispatch_tool`` runs: a registered tool's arguments against
    its full schema (``_closed_schema``), not the form clients are shown.

    Raises:
        ToolError: if the arguments do not satisfy the schema.
    """
    _check(_tool_validator(name), arguments)


def _check(validator: Any, arguments: dict[str, Any]) -> None:
    error = jsonschema.exceptions.best_match(validator.iter_errors(arguments))
    if error is not None:
        location = "/".join(str(part) for part in error.absolute_path)
        where = f" at '{location}'" if location else ""
        raise ToolError(f"Input validation error{where}: {error.message}")


@functools.cache
def _declared_names(name: str) -> frozenset[str]:
    """Every property name a registered tool's schema declares, at any depth."""
    names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            names.update(node.get("properties", {}))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(_REGISTRY[name][0]().input_schema)
    return frozenset(names)


@functools.cache
def _tool_validator(name: str) -> Any:
    """The validator of a registered tool, from its schema built and closed once."""
    return _validator(json.dumps(_closed_schema(name), sort_keys=True))


@functools.cache
def _closed_schema(name: str) -> dict:
    """A registered tool's input schema as validated (closed, with its root
    ``allOf``), built once.

    Validation and the integer coercion read this same object; it is never
    modified. Clients see ``all_tools()``, which flattens the root.
    """
    factory, _run = _REGISTRY[name]
    return _build(factory).input_schema


async def dispatch_tool(
    client: KimaiClient, name: str, arguments: dict[str, Any] | None
) -> list[TextContent]:
    """Route a tool call to its handler. Exceptions propagate to the caller's
    error handling (ToolError / KimaiAPIError -> error_result)."""
    entry = _REGISTRY.get(name)
    if entry is None:
        raise ToolError(
            f"Unknown tool: {name}. Available tools: {', '.join(_REGISTRY)}"
        )
    _factory, run = entry
    arguments = arguments or {}
    validate_call(name, arguments)
    arguments = _integers(_closed_schema(name), arguments)
    try:
        return await run(client, arguments)
    except pydantic.ValidationError as e:
        # A request model (*Form, *Filter) rejected a value the schema let
        # through (a sort field Kimai does not take, an ambiguous duration).
        # Say which and why, without pydantic's type codes and links. A
        # response model failing means Kimai sent something unexpected; that
        # is not the caller's input and propagates unchanged.
        if not e.title.endswith(("Form", "Filter")):
            raise
        raise ToolError(_format_input_error(e, _declared_names(name))) from None


def _integers(schema: dict, value: Any) -> Any:
    """``value`` with every integral float the schema types as integer made an int.

    JSON Schema's "integer" accepts 1.0, and 1.0 would reach Kimai as
    ``/timesheets/1.0`` (404) or ``size=10.0`` (400). Untyped values (a meta
    field's value) are left alone.
    """
    types = schema.get("type")
    types = types if isinstance(types, list) else [types]
    if isinstance(value, float) and value.is_integer() and "integer" in types:
        return int(value)
    if isinstance(value, list):
        items = schema.get("items", {})
        return [_integers(items, v) for v in value] if isinstance(items, dict) else value
    if isinstance(value, dict):
        properties = dict(schema.get("properties", {}))
        for branch in schema.get("allOf", []):
            for part in ("then", "else"):
                for key, sub in branch.get(part, {}).get("properties", {}).items():
                    properties.setdefault(key, {})
                    # a key typed in a branch (the per-type entity data) wins
                    if sub.get("properties") or sub.get("type"):
                        properties[key] = _merge(properties[key], sub)
        return {k: _integers(properties.get(k, {}), v) for k, v in value.items()}
    return value


def _merge(base: dict, extra: dict) -> dict:
    merged = {**base, **extra}
    merged["properties"] = {**base.get("properties", {}), **extra.get("properties", {})}
    return merged


def _format_input_error(error: "pydantic.ValidationError", declared: frozenset[str]) -> str:
    """One line per problem, naming the field as the caller sends it.

    Pydantic reports either spelling of a field, depending on how the handler
    built the model (``break_duration=...`` vs. ``**data``), while each tool
    schema declares one: the wire name for most forms (``break``), the Python
    name for filters (``order_by``) and for the rate data (``internal_rate``).
    The spelling the tool declares is the one reported.
    """
    model = getattr(models, error.title, None)
    fields = getattr(model, "model_fields", {})
    problems = []
    for detail in error.errors():
        loc = [str(part) for part in detail["loc"]]
        info = fields.get(loc[0]) if loc else None
        if info is None and loc:
            info = next((f for f in fields.values() if f.alias == loc[0]), None)
        if info is not None:
            python_name = next(n for n, f in fields.items() if f is info)
            spellings = [python_name, info.alias or python_name]
            loc[0] = next((s for s in spellings if s in declared), loc[0])
        field = ".".join(loc) or "input"
        problems.append(f"'{field}': {detail['msg'].removeprefix('Value error, ')}")
    return "Error: invalid value for " + "; ".join(problems)
