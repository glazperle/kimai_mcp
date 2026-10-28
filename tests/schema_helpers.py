"""Helpers for reading the `entity` tool's per-type data schemas in tests."""

from kimai_mcp.tools.entity_manager import data_slots, entity_tool


def entity_data_schema(entity_type: str, action: str = "create") -> dict:
    """The `data` sub-schema of one entity type and write action.

    The tool's `data` is an `anyOf` with one alternative per type and write
    action, in the order of `data_slots()`; users have one per action (create
    needs the password), so the action matters.
    """
    options = entity_tool().input_schema["properties"]["data"]["anyOf"]
    for option, (slot_type, actions) in zip(options, data_slots(), strict=True):
        if slot_type == entity_type and action in actions:
            return option
    raise AssertionError(f"{entity_type} {action} schema not found")
