"""Helpers for reading the `entity` tool's conditional JSON schema in tests."""

from kimai_mcp.tools.entity_manager import entity_tool


def entity_data_schema(entity_type: str) -> dict:
    """The create/update `data` sub-schema for one entity type.

    The tool schema is an `allOf` of `if type == X and action in (create,
    update) then data = {...}` branches; this returns the `data` object of the
    branch for ``entity_type``.
    """
    for branch in entity_tool().input_schema["allOf"]:
        given = branch.get("if", {}).get("properties", {})
        if given.get("type", {}).get("const") != entity_type:
            continue
        data = branch.get("then", {}).get("properties", {}).get("data")
        if data is not None:
            return data
    raise AssertionError(f"{entity_type} create/update schema not found")
