#!/usr/bin/env python3
"""Compare the client and its models against Kimai's own API sources.

Kimai builds its OpenAPI document from three inputs, all read here straight
from the Kimai repository at a given tag:

* ``config/packages/nelmio_api_doc.yaml`` - schema alias -> entity + serializer
  groups (e.g. ``CustomerCollection`` = ``Customer`` with the groups
  ``Default, Collection, Customer``)
* the entity sources and the traits they use - property -> serializer groups
* ``src/API/*Controller.php`` - route -> query parameters + response schema

Three checks run against those, each gating the exit code:

1. **Fields**: every field a response schema contains must be carried by the
   model we map that schema to (``SCHEMA_TO_MODEL``).
2. **Endpoints**: for every ``KimaiClient`` method, read from its source,
   a) the model it parses a response into must be the model of the schema the
      route declares (``/users/me`` is ``UserEntity``; parsing it as ``User``
      silently lost roles, teams and preferences),
   b) every query parameter Kimai accepts on that route must be sendable,
   c) a parameter with a fixed set of values (``orderBy: 'id|name|customer'``)
      must be typed with exactly that set, so the client neither sends a value
      Kimai rejects nor misses one it accepts,
   d) the route must not be one Kimai marks deprecated;
   and every current, non-internal core route must be called by some method.
3. **Duration grammar**: ``models._DURATION_ALTERNATIVES`` is compared verbatim
   with the ``$patterns`` array in ``src/Validator/Constraints/Duration.php``,
   because the client rejects input against it before Kimai sees the request.

Whether the *tools* then show those fields and expose those parameters is not
something the Kimai sources can answer; ``tests/test_read_coverage.py`` and
``tests/test_filter_coverage.py`` check that half offline in CI.

    python scripts/audit_api_models.py            # against the pinned version
    python scripts/audit_api_models.py 2.70.2     # after a Kimai release
    python scripts/audit_api_models.py 2.70.2 --source ../kimai   # local checkout

Exit code is 1 on any gap. Deliberate exceptions live in the ``EXPECTED_*``
tables below, each with its reason; extend those rather than silencing a check.
"""

from __future__ import annotations

import ast
import base64
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = "kimai/kimai"
DEFAULT_REF = "2.66.0"
CACHE = Path(__file__).parent / ".kimai-api-cache"
CLIENT_SOURCE = Path(__file__).parent.parent / "src" / "kimai_mcp" / "client.py"

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
    "ProjectExpanded": "ProjectExpanded",
    "Activity": "Activity",
    "ActivityCollection": "Activity",
    "ActivityEntity": "Activity",
    "ActivityExpanded": "ActivityExpanded",
    "TimesheetEntity": "TimesheetEntity",
    "TimesheetCollection": "TimesheetEntity",
    "TimesheetExpanded": "TimesheetExpanded",
    "TimesheetCollectionExpanded": "TimesheetExpanded",
    "TagEntity": "TagEntity",
    "User": "User",
    "UserCollection": "User",
    "UserEntity": "UserEntity",
    "Team": "Team",
    "TeamCollection": "Team",
    "TeamEntity": "Team",
    "Absence": "Absence",
    "Invoice": "Invoice",
    "InvoiceCollection": "Invoice",
    "Comment": "Comment",
    "CustomerRate": "Rate",
    "ProjectRate": "Rate",
    "ActivityRate": "Rate",
}

# Query parameters Kimai accepts that the client deliberately never sends:
# (route, parameter) -> reason.
EXPECTED_UNSENT = {
    ("/timesheets", "full"): (
        "full=true answers with the Expanded schema (objects instead of ids) on POST /timesheets; "
        "the client parses TimesheetEntity there"
    ),
}

# Core routes no client method calls: (METHOD, route) -> reason.
EXPECTED_UNUSED = {
    ("GET", "/invoices/{}/download"): "returns the invoice file (PDF etc.), not JSON",
}

# Deprecated routes a client method still calls: (METHOD, route) -> reason.
EXPECTED_DEPRECATED_USE: dict[tuple[str, str], str] = {}

# Client routes served by plugins, not by core Kimai; nothing to compare against.
PLUGIN_ROUTES = (
    "/absences",
    "/public-holidays",
    "/work-contract/",
    "/users/{}/api-token",
)

ALIAS_RE = re.compile(
    r"alias:\s*(?P<alias>\w+)\s*,\s*type:\s*App\\(?P<type>[\w\\]+)\s*,\s*groups:\s*\[(?P<groups>[^\]]*)\]"
)
GROUP_RE = re.compile(r"Groups\(\[(.*?)\]\)")
NAME_RE = re.compile(r"SerializedName\('([^']+)'\)")
PROP_RE = re.compile(r"^\s*(?:private|protected|public)\s+\S+\s+\$(\w+)")
TRAIT_USE_RE = re.compile(r"^\s{4}use\s+(\w+)\s*;")  # inside the class body
IMPORT_RE = re.compile(r"^use\s+App\\([\w\\]+)\s*;")

_local_source: Path | None = None


def fetch(path: str, ref: str) -> str:
    """Read a file from the Kimai repository, cached per (ref, path)."""
    if _local_source is not None:
        local = _local_source / path
        return local.read_text(encoding="utf-8") if local.exists() else ""
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


def list_dir(path: str, ref: str) -> list[str]:
    """File names in a directory of the Kimai repository."""
    if _local_source is not None:
        return sorted(p.name for p in (_local_source / path).iterdir())
    cached = CACHE / ref / (path.replace("/", "_") + ".dir")
    if cached.exists():
        return cached.read_text(encoding="utf-8").split()
    proc = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{path}?ref={ref}", "-q", ".[].name"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return []
    names = proc.stdout.split()
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text("\n".join(names), encoding="utf-8")
    return names


# --- 1. response fields vs models -------------------------------------------


def parse_schema_aliases(ref: str) -> dict:
    text = fetch("config/packages/nelmio_api_doc.yaml", ref)
    return {
        m.group("alias"): {
            "type": m.group("type"),
            "groups": {g.strip() for g in m.group("groups").split(",") if g.strip()},
        }
        for m in ALIAS_RE.finditer(text)
    }


def _groups(text: str) -> set:
    return {x.strip().strip("'\"") for x in text.split(",")}


def entity_fields(path: str, ref: str) -> list[tuple[str, set]]:
    """[(serialized name, {serializer groups})] for one entity, traits included.

    Covers the three ways Kimai declares a serialized field: a property with
    ``Groups``, a class-level ``VirtualProperty(..., options: [SerializedName,
    Groups])`` and a getter marked ``VirtualProperty`` (``metaFields``,
    ``preferences``, ``teams``). Traits (``BudgetTrait``, ``ColorTrait``) are
    resolved through the file's own ``use App\\...;`` imports.
    """
    source = fetch(path, ref)
    if not source:
        return []
    imports = {
        m.group(1).rsplit("\\", 1)[-1]: m.group(1)
        for line in source.splitlines() if (m := IMPORT_RE.match(line))
    }
    fields: list[tuple[str, set]] = []
    groups: set | None = None
    serialized: str | None = None
    virtual = False
    for line in source.splitlines():
        if "VirtualProperty(" in line and "options:" in line:
            # class-level: name and groups on the same line
            name, grp = NAME_RE.search(line), GROUP_RE.search(line)
            if name and grp:
                fields.append((name.group(1), _groups(grp.group(1))))
            continue
        if "VirtualProperty" in line:
            virtual = True
            continue
        if match := GROUP_RE.search(line):
            groups = _groups(match.group(1))
            continue
        if match := NAME_RE.search(line):
            serialized = match.group(1)
            continue
        if trait := TRAIT_USE_RE.match(line):
            qualified = imports.get(trait.group(1), "Entity\\" + trait.group(1))
            fields += entity_fields(f"src/{qualified.replace(chr(92), '/')}.php", ref)
            continue
        if prop := PROP_RE.match(line):
            if groups is not None:
                fields.append((serialized or prop.group(1), groups))
            groups, serialized, virtual = None, None, False
            continue
        if re.match(r"^\s*(?:abstract\s+)?(?:public|protected|private)\s+(?:static\s+)?function\s", line):
            if virtual and groups is not None and serialized:
                fields.append((serialized, groups))
            groups, serialized, virtual = None, None, False
    return fields


def model_aliases(class_name: str) -> set | None:
    from kimai_mcp import models

    cls = getattr(models, class_name, None)
    if cls is None:
        return None
    return {field.alias or name for name, field in cls.model_fields.items()}


def check_fields(ref: str, aliases: dict) -> list:
    sources: dict[str, list] = {}
    gaps = []
    for alias, cfg in sorted(aliases.items()):
        model_name = SCHEMA_TO_MODEL.get(alias)
        if model_name is None:
            continue
        php = cfg["type"]
        if php not in sources:
            sources[php] = entity_fields(f"src/{php.replace(chr(92), '/')}.php", ref)
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
    return gaps


# --- 2. client endpoints vs routes ------------------------------------------


@dataclass
class Route:
    method: str
    path: str  # parameters normalized to {}
    query: list[str]
    schemas: list[str]
    internal: bool
    deprecated: bool
    # query parameter -> its `requirements` regex, where Kimai declares one
    requirements: dict = field(default_factory=dict)


@dataclass
class ClientCall:
    name: str
    method: str
    path: str  # parameters normalized to {}
    built: set = field(default_factory=set)
    query: set = field(default_factory=set)
    # query key -> the Python type the client accepts for it
    types: dict = field(default_factory=dict)


def _attributes(lines: list[str]):
    """Yield (attribute lines, following code line); attributes may span lines."""
    attrs: list[str] = []
    buf, depth = "", 0
    for line in lines:
        stripped = line.strip()
        if depth == 0 and not stripped.startswith("#["):
            yield attrs, stripped
            if stripped:
                attrs = []
            continue
        buf += (" " if buf else "") + stripped
        depth += stripped.count("[") + stripped.count("(") - stripped.count("]") - stripped.count(")")
        if depth <= 0:
            attrs.append(buf)
            buf, depth = "", 0


def parse_routes(ref: str) -> list[Route]:
    routes = []
    for name in list_dir("src/API", ref):
        if not name.endswith("Controller.php"):
            continue
        source = fetch(f"src/API/{name}", ref)
        lines = source.splitlines()
        class_at = next((i for i, x in enumerate(lines) if re.match(r"\s*(final\s+|abstract\s+)?class\s", x)), None)
        if class_at is None:
            continue
        prefix = ""
        for line in lines[:class_at]:
            if m := re.search(r"#\[Route\(path: '([^']*)'", line):
                prefix = m.group(1)
        for attrs, code in _attributes(lines[class_at + 1:]):
            if not code.startswith("public function"):
                continue
            route = next((a for a in attrs if a.startswith("#[Route(")), None)
            if route is None:
                continue
            path = re.search(r"path: '([^']*)'", route)
            methods = re.search(r"methods: \[([^\]]*)\]", route)
            schemas: list[str] = []
            for attr in attrs:
                if attr.startswith(("#[OA\\RequestBody", "#[OA\\Parameter")):
                    continue
                schemas += re.findall(r"ref: '#/components/schemas/(\w+)'", attr)
            full = re.sub(r"\{[^}]+\}", "{}", prefix + (path.group(1) if path else ""))
            requirements = {
                m.group(1): m.group(2)
                for a in attrs
                if (m := re.search(r"Rest\\QueryParam\(name: '([^']+)'.*?requirements: '([^']*)'", a))
            }
            for method in (methods.group(1) if methods else "'GET'").replace("'", "").split(","):
                routes.append(Route(
                    method=method.strip(),
                    path=full.rstrip("/") or "/",
                    query=[q for a in attrs for q in re.findall(r"Rest\\QueryParam\(name: '([^']+)'", a)],
                    schemas=list(dict.fromkeys(schemas)),
                    internal=any("'internal' => true" in a for a in attrs),
                    deprecated=any(a.startswith("#[OA\\") and "deprecated: true" in a for a in attrs),
                    requirements=requirements,
                ))
    return routes


def _render_path(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "{}"
            for part in node.values
        )
    return None


def parse_client() -> list[ClientCall]:
    """Every _request() call in KimaiClient with the models and query keys around it."""
    import typing

    from kimai_mcp import models
    from kimai_mcp.client import KimaiClient

    model_names = {n for n in dir(models) if isinstance(getattr(models, n), type)}
    tree = ast.parse(CLIENT_SOURCE.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "KimaiClient")
    calls = []
    for fn in cls.body:
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        built = {
            n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in model_names
        }
        # Query keys: fields of a *Filter argument, plus literal keys put into `params`.
        hints = typing.get_type_hints(getattr(KimaiClient, fn.name))
        query: set = set()
        types: dict = {}
        for arg in fn.args.args:
            for name in re.findall(r"\b(\w+Filter)\b", ast.unparse(arg.annotation) if arg.annotation else ""):
                for n, f in getattr(models, name).model_fields.items():
                    query.add(f.alias or n)
                    types[f.alias or n] = f.annotation
        for node in ast.walk(fn):
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.value, ast.Name) and "params" in node.value.id:
                query.add(str(node.slice.value).removesuffix("[]"))
            # params["orderBy"] = order_by: the key takes the argument's type
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in hints:
                for target in node.targets:
                    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
                        types[str(target.slice.value)] = hints[node.value.id]
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) \
                    and any(isinstance(t, ast.Name) and "params" in t.id for t in node.targets):
                query |= {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "_request" and len(node.args) >= 2:
                path = _render_path(node.args[1])
                if path is None:
                    continue
                calls.append(ClientCall(
                    name=fn.name,
                    method=node.args[0].value,
                    path=path,
                    built=built,
                    query=query,
                    types=types,
                ))
    return calls


def _matches(call: ClientCall, route: Route) -> bool:
    """Segment-wise: a bare ``{}`` (an id) only matches a route parameter.

    That keeps ``/timesheets/{id}`` off ``/timesheets/recent``, while a segment
    with literal text around the placeholder (``/{entity}s/...`` for comments)
    still matches each concrete route it can produce.
    """
    if call.method != route.method:
        return False
    ours, theirs = call.path.split("/"), route.path.split("/")
    if len(ours) != len(theirs):
        return False
    for mine, other in zip(ours, theirs):
        if mine == "{}":
            if other != "{}":
                return False
        elif "{}" in mine:
            if not re.fullmatch(re.escape(mine).replace(r"\{\}", "[^/]+"), other):
                return False
        elif mine != other:
            return False
    return True


ALTERNATION_RE = re.compile(r"^\w+(\|\w+)+$")
# Parameters whose values are names; the client must type them as a Literal so
# a value Kimai rejects (or a new one it accepts) shows up here.
NAMED_VALUES = {"orderBy", "order", "status"}


def _literal_values(annotation) -> set | None:
    """Values of every Literal inside an annotation (through Optional/list)."""
    import typing

    if typing.get_origin(annotation) is typing.Literal:
        return {str(a) for a in typing.get_args(annotation)}
    values = None
    for arg in typing.get_args(annotation):
        inner = _literal_values(arg)
        if inner is not None:
            values = (values or set()) | inner
    return values


def check_values(call: ClientCall, route: Route) -> list[str]:
    """Problems with the values the client allows for enumerated parameters."""
    problems = []
    for param, requirement in route.requirements.items():
        if not ALTERNATION_RE.match(requirement):
            continue
        allowed = set(requirement.split("|"))
        ours = _literal_values(call.types.get(param))
        if ours is None:
            if param in NAMED_VALUES:
                problems.append(f"'{param}' is not typed as a Literal; Kimai only takes {sorted(allowed)}")
            continue
        if ours - allowed:
            problems.append(f"'{param}' allows {sorted(ours - allowed)}, which Kimai rejects")
        if allowed - ours:
            problems.append(f"'{param}' cannot send {sorted(allowed - ours)}, which Kimai accepts")
    return problems


def check_endpoints(ref: str) -> list:
    from kimai_mcp import models

    routes = parse_routes(ref)
    if not routes:
        print(f"[SKIP] could not read src/API at {ref}")
        return []
    calls = parse_client()
    gaps = []
    used: set = set()

    for call in calls:
        matched = [r for r in routes if _matches(call, r)]
        if not matched:
            if call.path.startswith(PLUGIN_ROUTES):
                continue
            print(f"[GAP ] {call.name:28} {call.method} {call.path}: no such route in Kimai {ref}")
            gaps.append({"client": call.name, "route": f"{call.method} {call.path}", "problem": "unknown route"})
            continue
        for route in matched:
            used.add((route.method, route.path))
            if route.deprecated and (route.method, route.path) not in EXPECTED_DEPRECATED_USE:
                print(f"[GAP ] {call.name:28} {route.method} {route.path}: Kimai marks this route deprecated")
                gaps.append({"client": call.name, "route": f"{route.method} {route.path}",
                             "problem": "calls a deprecated route"})
            expected = {SCHEMA_TO_MODEL[s] for s in route.schemas if s in SCHEMA_TO_MODEL}
            wrong = {
                b for b in call.built
                if expected and not any(issubclass(getattr(models, b), getattr(models, e)) for e in expected)
                and not b.endswith(("Form", "Filter"))
            }
            if wrong:
                print(f"[GAP ] {call.name:28} {route.method} {route.path}: parses {sorted(wrong)}, "
                      f"Kimai sends {route.schemas} -> {sorted(expected)}")
                gaps.append({"client": call.name, "route": f"{route.method} {route.path}",
                             "problem": f"parsed as {sorted(wrong)}, schema is {sorted(expected)}"})
            for problem in check_values(call, route):
                print(f"[GAP ] {call.name:28} {route.method} {route.path}: {problem}")
                gaps.append({"client": call.name, "route": f"{route.method} {route.path}", "problem": problem})
            unsent = [q for q in route.query if q not in call.query and (route.path, q) not in EXPECTED_UNSENT]
            if unsent:
                print(f"[GAP ] {call.name:28} {route.method} {route.path}: cannot send query {unsent}")
                gaps.append({"client": call.name, "route": f"{route.method} {route.path}",
                             "problem": f"query parameters never sent: {unsent}"})

    for route in routes:
        key = (route.method, route.path)
        if route.internal or route.deprecated or key in used or key in EXPECTED_UNUSED:
            continue
        print(f"[GAP ] {'(no client method)':28} {route.method} {route.path}")
        gaps.append({"client": None, "route": f"{route.method} {route.path}", "problem": "no client method"})

    # Excuses that no longer excuse anything would hide the next real gap.
    known = {(r.method, r.path) for r in routes}
    for key in EXPECTED_UNUSED:
        if key in used or key not in known:
            print(f"[GAP ] EXPECTED_UNUSED entry {key} is stale ({'used' if key in used else 'no such route'})")
            gaps.append({"client": None, "route": f"{key[0]} {key[1]}", "problem": "stale EXPECTED_UNUSED entry"})
    deprecated = {(r.method, r.path) for r in routes if r.deprecated}
    for key in EXPECTED_DEPRECATED_USE:
        if key not in used or key not in deprecated:
            print(f"[GAP ] EXPECTED_DEPRECATED_USE entry {key} is stale")
            gaps.append({"client": None, "route": f"{key[0]} {key[1]}", "problem": "stale EXPECTED_DEPRECATED_USE entry"})
    accepted = {(r.path, q) for r in routes for q in r.query}
    for key in EXPECTED_UNSENT:
        if key not in accepted:
            print(f"[GAP ] EXPECTED_UNSENT entry {key} is stale (Kimai no longer accepts it)")
            gaps.append({"client": None, "route": key[0], "problem": "stale EXPECTED_UNSENT entry"})

    print(f"\n{len(calls)} client calls checked against {len(routes)} routes")
    return gaps


# --- 3. duration grammar -----------------------------------------------------

DURATION_QUOTED_RE = re.compile(r"^\s*'([^']+)',?\s*$", re.MULTILINE)


def check_duration_grammar(ref: str) -> bool:
    """Compare the local copy of Kimai's duration regex with the upstream one.

    `models._DURATION_ALTERNATIVES` is a hand transcription of the `$patterns`
    array in `src/Validator/Constraints/Duration.php`. It is used to reject
    input locally, so a widened upstream grammar would make this client refuse
    a duration Kimai accepts, with a confident message and no 400 to notice.
    """
    from kimai_mcp.models import _DURATION_ALTERNATIVES

    source = fetch("src/Validator/Constraints/Duration.php", ref)
    if not source:
        print("[SKIP] duration grammar: could not read src/Validator/Constraints/Duration.php")
        return True
    start = source.find("$patterns = [")
    end = source.find("];", start) if start >= 0 else -1
    if start < 0 or end < 0:
        print("[SKIP] duration grammar: $patterns array not found in Duration.php (layout changed?)")
        return True
    upstream = DURATION_QUOTED_RE.findall(source[start:end])
    ours = list(_DURATION_ALTERNATIVES)
    if upstream == ours:
        print(f"[OK  ] duration grammar: {len(ours)} alternatives match Duration.php")
        return True
    print("[GAP ] duration grammar differs from Duration.php")
    print(json.dumps({"upstream": upstream, "ours": ours}, indent=2))
    return False


def main() -> int:
    global _local_source
    args = sys.argv[1:]
    if "--source" in args:
        at = args.index("--source")
        _local_source = Path(args[at + 1])
        del args[at:at + 2]
    ref = args[0] if args else DEFAULT_REF

    aliases = parse_schema_aliases(ref)
    if not aliases:
        print(f"could not read the schema config for {ref} (is `gh` authenticated?)")
        return 2
    print(f"Kimai {ref}: {len(aliases)} schema aliases\n")

    field_gaps = check_fields(ref, aliases)
    print()
    endpoint_gaps = check_endpoints(ref)
    print()
    grammar_ok = check_duration_grammar(ref)

    print(f"\n{len(field_gaps)} schema(s) expose fields no model carries")
    if field_gaps:
        print(json.dumps(field_gaps, indent=2))
    print(f"{len(endpoint_gaps)} endpoint gap(s)")
    if endpoint_gaps:
        print(json.dumps(endpoint_gaps, indent=2))
    return 1 if field_gaps or endpoint_gaps or not grammar_ok else 0


if __name__ == "__main__":
    sys.exit(main())
