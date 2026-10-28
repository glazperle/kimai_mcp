"""JSON Schema checks shared by the tool registry and a tool's own checks."""
import functools
import json
from typing import Any

import jsonschema

from .errors import ToolError


def close_objects(schema: dict) -> None:
    """Set ``additionalProperties: false`` on every input object, in place.

    Reaches the root, everything below ``properties`` and ``items``, and the
    alternatives of an ``anyOf`` (the entity tool's per-type ``data``). An
    explicit ``additionalProperties`` is left as it is.
    """
    if "properties" in schema:
        schema.setdefault("additionalProperties", False)
        for sub in schema["properties"].values():
            if isinstance(sub, dict):
                close_objects(sub)
    if isinstance(schema.get("items"), dict):
        close_objects(schema["items"])
    for option in schema.get("anyOf", []):
        close_objects(option)


@functools.lru_cache(maxsize=64)
def _validator(schema_json: str) -> Any:
    """A checked validator per distinct schema (keyed by its JSON text)."""
    schema = json.loads(schema_json)
    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    return validator_class(schema)


def validator_for(schema: dict) -> Any:
    """The cached validator of ``schema``.

    jsonschema.validate() checks the schema itself against the meta-schema on
    every call, ~70 ms for the entity schema; a cached validator ~0.2 ms.
    """
    return _validator(json.dumps(schema, sort_keys=True))


def check(validator: Any, instance: Any, at: tuple[str, ...] = ()) -> None:
    """Raise a ToolError naming the most relevant problem, if there is one.

    ``at`` is where ``instance`` sits in the tool's arguments, so the error
    names the place the caller wrote.
    """
    error = jsonschema.exceptions.best_match(validator.iter_errors(instance))
    if error is not None:
        location = "/".join(str(part) for part in (*at, *error.absolute_path))
        where = f" at '{location}'" if location else ""
        raise ToolError(f"Input validation error{where}: {error.message}")
