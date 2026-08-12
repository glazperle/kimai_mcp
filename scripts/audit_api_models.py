#!/usr/bin/env python3
"""Compare the Pydantic models against Kimai's own OpenAPI schema definitions.

Kimai builds its OpenAPI document from two inputs:

* ``config/packages/nelmio_api_doc.yaml`` - schema alias -> entity + serializer
  groups (e.g. ``CustomerCollection`` = ``Customer`` with the groups
  ``Default, Collection, Customer``)
* the entity sources - property -> serializer groups

This script reads both straight from the Kimai repository at a given tag and
reports every field a response contains that our models would silently drop.
It needs no Kimai instance, only the ``gh`` CLI for the raw file access.

    python scripts/audit_api_models.py            # against the pinned version
    python scripts/audit_api_models.py 2.66.0     # after a Kimai release

Exit code is 1 when a schema exposes a field no model carries, so it can gate
an API-compliance review. Fields listed in EXPECTED_UNMODELLED are ignored;
add to that list (with a reason) rather than silencing the whole check.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = "kimai/kimai"
DEFAULT_REF = "2.65.0"
CACHE = Path(__file__).parent / ".kimai-api-cache"

# Serialized by Kimai, deliberately not modelled:
#   color-safe   duplicates `color` with a fallback applied
#   apiToken     UI flag; the name invites confusion with a credential
EXPECTED_UNMODELLED = {"color-safe", "apiToken"}

# Response schema alias -> model class in kimai_mcp.models
SCHEMA_TO_MODEL = {
    "Customer": "Customer",
    "CustomerCollection": "Customer",
    "CustomerEntity": "Customer",
    "Project": "Project",
    "ProjectCollection": "Project",
    "ProjectEntity": "Project",
    "ProjectExpanded": "Project",
    "Activity": "Activity",
    "ActivityCollection": "Activity",
    "ActivityEntity": "Activity",
    "ActivityExpanded": "Activity",
    "TimesheetEntity": "TimesheetEntity",
    "TimesheetCollection": "TimesheetEntity",
    "TimesheetCollectionExpanded": "TimesheetEntity",
    "TagEntity": "TagEntity",
    "User": "User",
    "UserCollection": "User",
    "UserEntity": "UserEntity",
    "Team": "Team",
    "TeamCollection": "Team",
    "TeamEntity": "Team",
    "Absence": "Absence",
    "Invoice": "Invoice",
    "Comment": "Comment",
}

ALIAS_RE = re.compile(
    r"alias:\s*(?P<alias>\w+)\s*,\s*type:\s*App\\(?P<type>[\w\\]+)\s*,\s*groups:\s*\[(?P<groups>[^\]]*)\]"
)
GROUP_RE = re.compile(r"Groups\(\[(.*?)\]\)")
NAME_RE = re.compile(r"SerializedName\('([^']+)'\)")
PROP_RE = re.compile(r"^\s*(?:private|protected|public)\s+\S+\s+\$(\w+)")


def fetch(path: str, ref: str) -> str:
    """Read a file from the Kimai repository, cached per (ref, path)."""
    cached = CACHE / ref / path.replace("/", "_")
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    proc = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{path}?ref={ref}", "-q", ".content"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return ""
    text = base64.b64decode(proc.stdout).decode("utf-8", "replace")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text, encoding="utf-8")
    return text


def parse_schema_aliases(ref: str) -> dict:
    text = fetch("config/packages/nelmio_api_doc.yaml", ref)
    return {
        m.group("alias"): {
            "type": m.group("type"),
            "groups": {g.strip() for g in m.group("groups").split(",") if g.strip()},
        }
        for m in ALIAS_RE.finditer(text)
    }


def entity_fields(source: str) -> list[tuple[str, set]]:
    """[(serialized name, {serializer groups})] for one entity source.

    Properties inherited from traits (color, budget, ...) are not visible here,
    which is why this audit is a lower bound and the live check in
    scripts/verify_against_kimai.py complements it.
    """
    fields: list[tuple[str, set]] = []
    groups: set | None = None
    serialized: str | None = None
    for line in source.splitlines():
        if match := GROUP_RE.search(line):
            groups = {x.strip().strip("'\"") for x in match.group(1).split(",")}
            continue
        if match := NAME_RE.search(line):
            serialized = match.group(1)
            continue
        if prop := PROP_RE.match(line):
            if groups is not None:
                fields.append((serialized or prop.group(1), groups))
            groups, serialized = None, None
    return fields


def model_aliases(class_name: str) -> set | None:
    from kimai_mcp import models

    cls = getattr(models, class_name, None)
    if cls is None:
        return None
    return {field.alias or name for name, field in cls.model_fields.items()}


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REF
    aliases = parse_schema_aliases(ref)
    if not aliases:
        print(f"could not read the schema config for {ref} (is `gh` authenticated?)")
        return 2
    print(f"Kimai {ref}: {len(aliases)} schema aliases\n")

    sources: dict[str, list] = {}
    gaps = []
    for alias, cfg in sorted(aliases.items()):
        model_name = SCHEMA_TO_MODEL.get(alias)
        if model_name is None:
            continue
        php = cfg["type"]
        if php not in sources:
            sources[php] = entity_fields(fetch(f"src/{php.replace(chr(92), '/')}.php", ref))
        if not sources[php]:
            print(f"[SKIP] {alias:28} could not read {php}")
            continue
        ours = model_aliases(model_name)
        if ours is None:
            print(f"[SKIP] {alias:28} no model named {model_name}")
            continue

        exposed = {n for n, groups in sources[php] if groups & cfg["groups"]}
        missing = exposed - ours - EXPECTED_UNMODELLED
        print(f"[{'GAP ' if missing else 'OK  '}] {alias:28} -> {model_name:16} "
              f"exposed={len(exposed):2} missing={sorted(missing) or '-'}")
        if missing:
            gaps.append({"schema": alias, "model": model_name, "missing": sorted(missing)})

    print(f"\n{len(gaps)} schema(s) expose fields no model carries")
    if gaps:
        print(json.dumps(gaps, indent=2))
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
