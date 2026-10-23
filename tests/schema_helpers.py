"""Helpers for reading the `entity` tool's conditional JSON schema in tests."""

from kimai_mcp.tools.entity_manager import entity_tool


def entity_data_schema(entity_type: str, action: str = "create") -> dict:
    """The `data` sub-schema of one entity type and write action.

    The tool schema is an `allOf` of `if type == X and action in (...) then
    data = {...}` branches; users have one per action (create needs the
    password), so the action matters.
    """
    for branch in entity_tool().input_schema["allOf"]:
        given = branch.get("if", {}).get("properties", {})
        if given.get("type", {}).get("const") != entity_type:
            continue
        if action not in given.get("action", {}).get("enum", [action]):
            continue
        data = branch.get("then", {}).get("properties", {}).get("data")
        if data is not None:
            return data
    raise AssertionError(f"{entity_type} create/update schema not found")
