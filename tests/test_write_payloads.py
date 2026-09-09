"""Guards against manufactured write fields.

Kimai builds every API form per token and per instance setting: ``billable``
needs ``edit_billable_*``, ``budget`` needs the budget permission, ``break``
needs the break-time setting, ``begin``/``end`` need a tracking mode that
allows API times (punch-in/out: ``view_other_timesheet``). A field that is on
the wire but not on the form fails the whole request with
``This form should not contain extra fields.``

The client sends everything that is not ``None``. So the only safe rule is:
whatever the caller did not say must not be on the wire, and Kimai applies its
own default. These tests pin that rule from both ends, independent of which
fields Kimai happens to gate in a given version:

1. every write action, driven with its minimal input, produces a payload whose
   keys are a subset of the caller's keys;
2. no request-body model has a non-``None`` default.

PR #29 (``billable=True`` on timesheet create) and the punch-mode ``begin``
regression are the two instances this file exists for.
"""

import inspect
import re

import pytest

from kimai_mcp import models
from kimai_mcp.tools.registry import dispatch_tool
from tests.test_tool_dispatch import ENTITY_CREATE_DATA, make_mock_client


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _allowed_keys(form, caller_keys) -> set[str]:
    """Wire names the caller's keys may legitimately turn into."""
    allowed: set[str] = set()
    fields = getattr(type(form), "model_fields", {})
    for key in caller_keys:
        allowed.add(key)
        allowed.add(_camel(key))
        for name, field in fields.items():
            if key in (name, field.alias, _camel(name)):
                allowed.add(field.alias or name)
    return allowed


def _payload(sent) -> dict:
    if isinstance(sent, dict):
        return sent
    return sent.model_dump(exclude_none=True, by_alias=True)


# (tool, arguments, client method that receives the body, caller data keys)
WRITE_CASES = [
    pytest.param(
        "timesheet",
        {"action": "create", "data": {"project": 1, "activity": 1}},
        "create_timesheet",
        id="timesheet-create-minimal",
    ),
    pytest.param(
        "timesheet",
        {"action": "update", "id": 10, "data": {"description": "x"}},
        "update_timesheet",
        id="timesheet-update-one-field",
    ),
    pytest.param(
        "timer",
        {"action": "start", "data": {"project": 1, "activity": 1}},
        "create_timesheet",
        id="timer-start-minimal",
    ),
    pytest.param(
        "absence",
        {"action": "create", "data": {"comment": "vacation", "date": "2026-01-10", "type": "holiday"}},
        "create_absence",
        id="absence-create-minimal",
    ),
    pytest.param(
        "comment",
        {"entity": "project", "entity_id": 1, "action": "create", "data": {"message": "hello"}},
        "create_comment",
        id="comment-create-minimal",
    ),
]

for _entity in ("customer", "project", "activity"):
    WRITE_CASES.append(pytest.param(
        "rate",
        {"entity": _entity, "entity_id": 1, "action": "add", "data": {"rate": 50}},
        f"add_{_entity}_rate",
        id=f"rate-{_entity}-add-minimal",
    ))

for _entity in ("customer", "project", "activity", "user", "team", "tag"):
    WRITE_CASES.append(pytest.param(
        "entity",
        {"type": _entity, "action": "create", "data": ENTITY_CREATE_DATA[_entity]},
        f"create_{_entity}",
        id=f"entity-{_entity}-create-minimal",
    ))

for _entity in ("customer", "project", "activity"):
    WRITE_CASES.append(pytest.param(
        "entity",
        {"type": _entity, "action": "update", "id": 1, "data": {"name": "Renamed"}},
        f"update_{_entity}",
        id=f"entity-{_entity}-update-one-field",
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "arguments", "client_method"), WRITE_CASES)
async def test_write_sends_only_caller_keys(tool, arguments, client_method):
    client = make_mock_client()

    await dispatch_tool(client, tool, arguments)

    call = getattr(client, client_method).await_args
    assert call is not None, f"{client_method} was not called"
    sent = call.args[-1]
    payload = _payload(sent)
    caller_keys = set(arguments["data"])
    extra = set(payload) - _allowed_keys(sent, caller_keys)
    assert not extra, (
        f"{tool} {arguments.get('action')} put fields on the wire the caller never "
        f"supplied: {sorted(extra)}. Kimai may not have them on the form for this "
        f"token or instance; omit them and let Kimai apply its default."
    )


@pytest.mark.asyncio
async def test_timer_start_leaves_begin_to_kimai():
    """Punch-in/out mode removes ``begin``/``end`` from the API form unless the
    token has ``view_other_timesheet``. Kimai uses the current timestamp when
    ``begin`` is absent, so sending one gains nothing and breaks plain users."""
    client = make_mock_client()

    await dispatch_tool(client, "timer", {"action": "start", "data": {"project": 1, "activity": 1}})

    payload = _payload(client.create_timesheet.await_args.args[0])
    assert "begin" not in payload
    assert "end" not in payload


@pytest.mark.asyncio
async def test_rate_add_requires_rate():
    """``rate`` is required by Kimai; defaulting it to 0 booked a zero rate."""
    from kimai_mcp.tools.errors import ToolError

    client = make_mock_client()
    with pytest.raises(ToolError, match="rate"):
        await dispatch_tool(
            client, "rate", {"entity": "project", "entity_id": 1, "action": "add", "data": {"user": 1}}
        )
    assert client.add_project_rate.await_args is None


def _request_body_models():
    for name, cls in inspect.getmembers(models, inspect.isclass):
        if cls.__module__ != models.__name__:
            continue
        if re.search(r"Form$", name) and hasattr(cls, "model_fields"):
            yield name, cls


@pytest.mark.parametrize(("name", "cls"), list(_request_body_models()))
def test_request_body_models_have_no_manufactured_defaults(name, cls):
    """A non-None default on a request model is sent on every write, whether
    or not the caller asked for it. Required or ``None``, nothing else."""
    offenders = {
        field_name: field.default
        for field_name, field in cls.model_fields.items()
        if not field.is_required() and (field.default is not None or field.default_factory is not None)
    }
    assert not offenders, f"{name} manufactures values: {offenders}"
