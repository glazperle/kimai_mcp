"""Consolidated Timesheet tools for all timesheet operations."""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import get_args

# Bounds the extra fetching for statistics so a huge date range cannot pull an
# unbounded number of pages into a single response.
MAX_STATS_RESULTS = 10000

from mcp.types import TextContent, Tool

from ..client import MAX_PAGE_SIZE, KimaiAPIError, KimaiClient
from ..models import (
    MetaFieldForm,
    SortOrder,
    TimesheetEditForm,
    TimesheetFilter,
    TimesheetOrderBy,
)
from ..text import one_line, quoted, value_text
from .batch_utils import execute_batch, format_batch_result
from .dates import parse_local_datetime, parse_local_end, parse_utc_datetime, whole_day
from .errors import ToolError
from .lookups import RecordNames, best_effort, record_names
from .search_term import is_literal_meta_value, is_meta_name
from .timesheet_analytics import TimesheetAnalytics, worked_hours
from .user_discovery import own_records_note, resolve_accessible_users


def timesheet_tool() -> Tool:
    """Define the consolidated timesheet management tool."""
    return Tool(
        name="timesheet",
        description="""Timesheet management for time entries.

COMMON TASKS:
- List my timesheets: action=list, filters={user_scope:"self"}
- List all timesheets: action=list, filters={user_scope:"all"}
- Create entry: action=create, data={project:ID, activity:ID, begin:"...", end:"..."}
- Export entries: action=batch_export, ids=[...]

NOTE: For running timers (no end time), use the 'timer' tool instead.""",
        input_schema={
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete", "duplicate", "export_toggle", "meta_update", "user_guide", "batch_delete", "batch_export"],
                    "description": (
                        "export_toggle flips the export flag; batch_export marks as exported. "
                        "user_guide explains user_scope and lists users."
                    )
                },
                "id": {
                    "type": "integer",
                    "description": "Required for get, update, delete, duplicate, export_toggle, meta_update"
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "batch_delete, batch_export"
                },
                "filters": {
                    "type": "object",
                    "description": (
                        "For list: one page ('page', 'size') with names and the total. calculate_stats "
                        "and meta read every record of the filter."
                    ),
                    "properties": {
                        "user_scope": {
                            "type": "string",
                            "enum": ["self", "all", "specific"],
                            "description": "Default self; specific needs 'user'"
                        },
                        "user": {
                            "type": "string",
                            "description": "User ID for user_scope=specific"
                        },
                        "project": {"type": "integer"},
                        "activity": {"type": "integer"},
                        "customer": {"type": "integer"},
                        "begin": {
                            "type": "string",
                            "description": "Local time, no offset or 'Z': YYYY-MM-DDThh:mm:ss"
                        },
                        "end": {
                            "type": "string",
                            "description": "Like begin; a date alone means the end of that day"
                        },
                        "exported": {"type": "integer", "enum": [0, 1]},
                        "active": {"type": "integer", "enum": [0, 1]},
                        "billable": {"type": "integer", "enum": [0, 1]},
                        "users": {
                            "type": "array", "items": {"type": "integer"},
                            "description": "Several user IDs at once; replaces user_scope/user."
                        },
                        "customers": {"type": "array", "items": {"type": "integer"}, "description": "Several customer IDs (added to 'customer')."},
                        "projects": {"type": "array", "items": {"type": "integer"}, "description": "Several project IDs (added to 'project')."},
                        "activities": {"type": "array", "items": {"type": "integer"}, "description": "Several activity IDs (added to 'activity')."},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "Tag names; entries carrying any of them."},
                        "order_by": {"type": "string", "enum": list(get_args(TimesheetOrderBy)), "description": "Sort field. Kimai's default: begin."},
                        "order": {"type": "string", "enum": list(get_args(SortOrder)), "description": "Kimai's default: DESC."},
                        "modified_after": {
                            "type": "string",
                            "description": "Only entries changed after this date-time, in UTC (Kimai stores it in UTC), format YYYY-MM-DDThh:mm:ss."
                        },
                        "page": {"type": "integer", "minimum": 1, "default": 1},
                        "size": {"type": "integer", "minimum": 1, "default": 50},
                        "term": {"type": "string"},
                        "meta": {
                            "type": "object",
                            "description": (
                                "Entries whose meta field 'name' equals 'value' (case-insensitive), e.g. "
                                "{name: 'issue_tracker_id', value: 'CA-376'}. No value: any; '': none. "
                                "A value with ':' needs Kimai 2.35+."
                            ),
                            "required": ["name"],
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"}
                            }
                        },
                        "include_user_list": {"type": "boolean", "default": False},
                        "calculate_stats": {"type": "boolean", "default": False},
                        "stats_format": {"type": "string", "enum": ["summary", "detailed", "json"], "default": "summary"},
                        "breakdown_by_year": {"type": "boolean", "default": False, "description": "Automatic beyond one year"}
                    }
                },
                "data": {
                    "type": "object",
                    "description": "For create/update",
                    "properties": {
                        "project": {"type": "integer"},
                        "activity": {"type": "integer"},
                        "begin": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Omit to start at the current server time."
                        },
                        "end": {"type": "string", "format": "date-time"},
                        "description": {"type": "string"},
                        "tags": {"type": "string"},
                        "user": {"type": "integer"},
                        "billable": {
                            "type": "boolean",
                            "description": "Needs edit_billable_own/other_timesheet; omit for Kimai's default"
                        },
                        "fixedRate": {"type": "number"},
                        "hourlyRate": {"type": "number"},
                        "exported": {
                            "type": "boolean",
                            "description": "Needs edit_export_own/other_timesheet"
                        },
                        "break": {
                            "type": ["integer", "string"],
                            "description": (
                                "An integer is SECONDS (900 = 15 min); a string needs a unit ('15m', '0:15'). "
                                "Only where Kimai's 'Break time' setting is on, else the request fails."
                            )
                        }
                    }
                },
                "meta": {
                    "type": "array",
                    "description": "For meta_update",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {}
                        }
                    }
                },
                "show_users": {
                    "type": "boolean",
                    "description": "user_guide: list the users",
                    "default": True
                }
            }
        }
    )


def timer_tool() -> Tool:
    """Define the timer management tool."""
    return Tool(
        name="timer",
        description="""Timer management for running time tracking.

- Start timer: action=start, data={project:ID, activity:ID}
- Stop timer: action=stop, id=TIMESHEET_ID
- Show active: action=active
- Recent activities: action=recent lists the latest record of each customer/project/activity
  combination you worked on; restart one with action=restart, id=TIMESHEET_ID
- Favorites (Kimai 2.66+): action=favorites lists the user's favorite timesheets (templates to restart);
  action=favorite / action=unfavorite, id=TIMESHEET_ID toggles one. Needs start_own_timesheet; own records only.

NOTE: Creates timesheet entries without end time. Use 'timesheet' tool for completed entries.""",
        input_schema={
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "restart", "active", "recent", "favorites", "favorite", "unfavorite"],
                    "description": "The timer action to perform"
                },
                "id": {
                    "type": "integer",
                    "description": "Timesheet ID (required for stop, restart, favorite and unfavorite actions)"
                },
                "data": {
                    "type": "object",
                    "description": "Data for start action",
                    "properties": {
                        "project": {"type": "integer", "description": "Project ID"},
                        "activity": {"type": "integer", "description": "Activity ID"},
                        "description": {"type": "string", "description": "Timer description"},
                        "tags": {"type": "string", "description": "Comma-separated tags"}
                    }
                },
                "size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Number of recent activities to return (for recent action). Kimai caps it at 100.",
                    "default": 10
                },
                "begin": {
                    "type": "string",
                    "description": "Only entries after this local date/time, no offset or 'Z' (YYYY-MM-DDTHH:MM:SS, for recent action)"
                }
            }
        }
    )


async def handle_timesheet(client: KimaiClient, **params) -> list[TextContent]:
    """Handle consolidated timesheet operations."""
    action = params.get("action")
    
    if action == "list":
        return await _handle_timesheet_list(client, params.get("filters", {}))
    elif action == "get":
        return await _handle_timesheet_get(client, params.get("id"))
    elif action == "create":
        return await _handle_timesheet_create(client, params.get("data", {}))
    elif action == "update":
        return await _handle_timesheet_update(client, params.get("id"), params.get("data", {}))
    elif action == "delete":
        return await _handle_timesheet_delete(client, params.get("id"))
    elif action == "duplicate":
        return await _handle_timesheet_duplicate(client, params.get("id"))
    elif action == "export_toggle":
        return await _handle_timesheet_export_toggle(client, params.get("id"))
    elif action == "meta_update":
        return await _handle_timesheet_meta_update(client, params.get("id"), params.get("meta", []))
    elif action == "user_guide":
        return await _handle_timesheet_user_guide(client, params.get("show_users", True))
    elif action == "batch_delete":
        return await _handle_batch_delete(client, params.get("ids", []))
    elif action == "batch_export":
        return await _handle_batch_export(client, params.get("ids", []))
    else:
        raise ToolError(
            f"Error: Unknown action '{action}'. Valid actions: list, get, create, update, delete, duplicate, export_toggle, meta_update, user_guide, batch_delete, batch_export"
        )


async def handle_timer(client: KimaiClient, **params) -> list[TextContent]:
    """Handle timer operations."""
    action = params.get("action")
    
    if action == "start":
        return await _handle_timer_start(client, params.get("data", {}))
    elif action == "stop":
        return await _handle_timer_stop(client, params.get("id"))
    elif action == "restart":
        return await _handle_timer_restart(client, params.get("id"))
    elif action == "active":
        return await _handle_timer_active(client)
    elif action == "recent":
        return await _handle_timer_recent(client, params.get("size", 10), params.get("begin"))
    elif action == "favorites":
        return await _handle_timer_favorites(client)
    elif action == "favorite":
        return await _handle_timer_favorite(client, params.get("id"), add=True)
    elif action == "unfavorite":
        return await _handle_timer_favorite(client, params.get("id"), add=False)
    else:
        raise ToolError(
            f"Error: Unknown action '{action}'. Valid actions: start, stop, restart, active, recent, favorites, favorite, unfavorite"
        )


def _format_meta_fields(meta_fields: list[dict] | None) -> str | None:
    """Render the non-empty meta fields as ``name=value, ...`` (None if there are none).

    Kimai serializes the stored, visible meta rows; a stored row without a
    value arrives as ``{"name": ..., "value": null}`` and is skipped. A value
    with a separator, a quote, a line break or outer whitespace is JSON-quoted
    (``text.value_text``): unambiguous in a listing and lossless in ``get``.
    """
    parts = [
        f"{one_line(field.get('name'))}={value_text(field.get('value'))}"
        for field in meta_fields or []
        if field.get("value") not in (None, "")
    ]
    return ", ".join(parts) if parts else None


def _meta_value(meta_fields: list[dict] | None, name: str) -> str | None:
    """The record's value of meta field ``name`` ('' for null), None without a row.

    Kimai serializes the *stored* meta rows that are visible. A record saved
    before the field existed has no row at all, one saved while the field was
    hidden has a row that is not sent; both arrive without the field. Names
    are compared case-insensitively, like Kimai's own search does.
    """
    for field in meta_fields or []:
        if str(field.get("name", "")).casefold() == name.casefold():
            return "" if field.get("value") is None else str(field["value"])
    return None


def _filter_by_meta(timesheets: list, name: str, wanted: str | None) -> tuple[list, str]:
    """Exact, case-insensitive meta match; ``wanted=None`` means "has any value".

    Returns the matches and a note about the records that cannot be checked
    here because they arrive without the field (no stored row, or a row saved
    while the field was hidden; the two look the same). Such a record is kept,
    and counted in the note, when it may match: for an empty search, and when
    Kimai's term asked for this value or for "any value". It is left out, and
    counted, when Kimai could only be asked whether *some* value is stored
    because this value cannot be expressed in its term syntax. When the name
    itself cannot be a term (whitespace or ':'), Kimai was not asked at all:
    only records that show the field are matched, and the note says so
    instead of counting every other record in the period.
    """
    term = _meta_search_term(name, wanted)
    any_value = term == f"{name}:*"
    name_searchable = _meta_search_term(name, None) is not None
    kept, unchecked, left_out, unsearched = [], 0, 0, 0
    for ts in timesheets:
        actual = _meta_value(ts.meta_fields, name)
        if actual is None:
            if wanted == "" or (term is not None and (wanted is None or not any_value)):
                kept.append(ts)
                unchecked += 1
            elif not name_searchable:
                unsearched += 1
            else:
                # Kimai could only be asked whether some value is stored
                # (fallback name:*), so nothing is known about this one.
                left_out += 1
        elif (actual != "") if wanted is None else (actual.casefold() == wanted.casefold()):
            kept.append(ts)

    notes = []
    if unchecked and wanted == "":
        notes.append(f"{unchecked} of these have no visible value for '{name}': saved before the field existed "
                     "(empty) or while it was hidden (value unknown).")
    elif unchecked and wanted is None:
        notes.append(f"{unchecked} of these store '{name}' hidden; Kimai reports a stored value, which may be "
                     "empty and cannot be checked here.")
    elif unchecked:
        notes.append(f"{unchecked} of these matched Kimai's substring search on a hidden '{name}' and are not "
                     "checked exactly.")
    if left_out:
        notes.append(f"{left_out} record(s) with a hidden '{name}' were left out: their value cannot be checked, "
                     "and Kimai's search cannot express this one.")
    if unsearched:
        notes.append(f"Kimai's search cannot address a meta field named '{name}' (whitespace or ':'), so only "
                     "records that show the field were checked; is this the field's internal name?")
    return kept, "".join(f"Note: {n}\n\n" for n in notes)


def _meta_search_term(name: str, value: str | None) -> str | None:
    """Translate a meta filter into Kimai's ``name:value`` search term syntax.

    Kimai matches ``name:value`` with ``LIKE '%value%'`` (so ``CA-376`` also
    returns ``CA-3760``), which makes the server-side term a pre-filter only;
    the exact comparison happens afterwards in ``_handle_timesheet_list``.
    A value the term cannot express literally (``search_term``) falls back
    to ``name:*`` (any value).
    Returns None when no term may be sent: the name cannot be expressed, or
    the value is empty. Kimai turns ``name:""`` into "value IS NULL or no such
    field", which misses a value cleared to ``''`` (all ``meta_update`` can
    store), so empty values are matched here only.
    """
    if not is_meta_name(name) or value == "":
        return None
    if value is None or not is_literal_meta_value(value):
        return f"{name}:*"
    return f"{name}:{value}"


# Timesheet action handlers
async def _handle_timesheet_list(client: KimaiClient, filters: dict) -> list[TextContent]:
    """Handle timesheet list action.

    The listing is one page (``page``, ``size``) of Kimai's, Expanded so the
    rows carry names, with the total from Kimai's pagination headers.
    Statistics and the exact meta match need every record of the filter: they
    page through all of it (up to MAX_STATS_RESULTS), and the listing shows
    the requested page of what matched.
    """

    # Handle user scope
    user_scope = filters.get("user_scope", "self")
    user_filter = None

    if filters.get("users"):
        # Several users replace the scope: Kimai adds `user` to `users`, so
        # sending the current user as well would mix their records in.
        user_scope = "users"
    elif user_scope == "self":
        current_user = await client.get_current_user()
        user_filter = str(current_user.id)
    elif user_scope == "specific":
        user_filter = filters.get("user")
        if not user_filter:
            raise ToolError("Error: 'user' parameter required when user_scope is 'specific'")
    elif user_scope == "all":
        user_filter = "all"  # API requires explicit "all" to return all users' timesheets

    begin_datetime = parse_local_datetime(filters["begin"], "begin") if filters.get("begin") else None
    end_datetime = whole_day(begin_datetime, parse_local_end(filters["end"], "end") if filters.get("end") else None)

    meta_filter = filters.get("meta")
    term = filters.get("term")
    if meta_filter is not None:
        if not isinstance(meta_filter, dict) or not meta_filter.get("name"):
            raise ToolError("Error: 'meta' filter requires a 'name', e.g. {name: 'issue_tracker_id', value: 'CA-376'}")
        meta_term = _meta_search_term(meta_filter["name"], meta_filter.get("value"))
        if meta_term:
            # Kimai ANDs the space-separated parts of a search term.
            term = f"{term} {meta_term}" if term else meta_term

    timesheet_filter = TimesheetFilter(
        user=user_filter,
        users=filters.get("users"),
        project=filters.get("project"),
        projects=filters.get("projects"),
        activity=filters.get("activity"),
        activities=filters.get("activities"),
        customer=filters.get("customer"),
        customers=filters.get("customers"),
        tags=filters.get("tags"),
        begin=begin_datetime,
        end=end_datetime,
        modified_after=(
            parse_utc_datetime(filters["modified_after"], "modified_after")
            if filters.get("modified_after") else None
        ),
        exported=filters.get("exported"),
        active=filters.get("active"),
        billable=filters.get("billable"),
        order_by=filters.get("order_by"),
        order=filters.get("order"),
        term=term,
    )

    # int(): a direct caller may pass 2.0 (dispatch_tool coerces, this does not).
    requested_page = int(filters.get("page") or 1)
    page_size = min(int(filters.get("size") or 50), MAX_PAGE_SIZE)
    calculate_stats = bool(filters.get("calculate_stats"))
    # The schema default is not applied server-side, so default here.
    stats_format = filters.get("stats_format", "summary")
    lists_rows = not (calculate_stats and stats_format == "summary")
    # Statistics cover the whole filter. So does the exact meta match: Kimai
    # paginates its LIKE pre-filter, so a page full of near-misses would hide
    # the exact matches on later pages.
    fetch_everything = calculate_stats or meta_filter is not None

    if fetch_everything:
        fetched, fetched_all = await client.get_timesheets(
            timesheet_filter.model_copy(update={"size": MAX_PAGE_SIZE}), max_results=MAX_STATS_RESULTS
        )
        capped = not fetched_all  # the record limit stopped the fetch
    else:
        # Expanded rows: names instead of IDs.
        page_filter = timesheet_filter.model_copy(update={"page": requested_page, "size": page_size, "full": "true"})
        try:
            page = await client.get_timesheet_page(page_filter)
        except KimaiAPIError as e:
            # Kimai answers a page past the end with 404 instead of an empty list.
            if e.status_code != 404 or requested_page == 1:
                raise
            return [TextContent(
                type="text",
                text=f"Page {requested_page} is past the last page of timesheets for this filter; use a lower 'page'.",
            )]
        fetched = page.rows
        capped = False

    # The server-side term is a substring pre-filter (see _meta_search_term);
    # narrow it down to exact matches here, before the statistics see the
    # records and before the requested page is cut out.
    matched, meta_note = fetched, ""
    if meta_filter is not None:
        matched, meta_note = _filter_by_meta(fetched, meta_filter["name"], meta_filter.get("value"))

    first = (requested_page - 1) * page_size
    show_user = user_scope != "self"
    names = RecordNames()
    if fetch_everything:
        shown = matched[first:first + page_size]
        found = len(matched)
        more = first + page_size < found
        certain = True
        # These rows carry IDs; the names come from the listings, fetched only
        # for what is used: listed rows, the projects of the statistics, the
        # customers of a customer filter (through the projects).
        named_rows = bool(shown) and lists_rows
        asks_customer = bool(filters.get("customers")) or filters.get("customer") is not None
        if named_rows or (calculate_stats and matched) or (asks_customer and fetched):
            names = await record_names(
                client,
                activities_of={ts.project for ts in shown} if named_rows else None,
                users=named_rows and show_user,
            )
    else:
        shown = matched
        # Without Kimai's headers (a proxy may drop them) only this page is known.
        found = page.total
        more = page.has_more
        certain = page.counted

    async def all_records_of(user_id: int) -> bool:
        """Whether every record of the filter, not only those read, is ``user_id``'s."""
        if not fetch_everything and requested_page == 1 and not more:
            return True
        if fetch_everything or found is None:
            # Everything read, unless the record limit cut it off.
            return fetch_everything and not capped
        # One record of the same filter for that user alone: the same total
        # means nobody else has any.
        probe = timesheet_filter.model_copy(update={"user": str(user_id), "users": None, "page": 1, "size": 1})
        own = await best_effort(client.get_timesheet_page(probe))
        return own is not None and own.total == found

    who = {
        "all": "for all users",
        "specific": f"for user {user_filter}",
        "users": f"for users {', '.join(map(str, filters.get('users') or []))}",
    }.get(user_scope, "for current user")
    if found is None:
        result = f"Found {len(shown)} timesheets {who} on page {requested_page}"
    else:
        result = f"Found {'at least ' if capped else ''}{found} timesheets {who}"
        if lists_rows and (requested_page > 1 or found > len(shown)):
            result += f", showing {first + 1}-{first + len(shown)}" if shown else f", none on page {requested_page}"
    result += "\n\n"

    if meta_filter is not None:
        wanted = meta_filter.get("value")
        result += f"Meta filter: {meta_filter['name']}={'<any>' if wanted is None else wanted}\n\n"
        result += meta_note

    if any(word.split(":", 1)[1] in ("~", '""') for word in (filters.get("term") or "").split() if ":" in word):
        # SearchHelper joins the meta rows without a condition for these two,
        # and the count has no DISTINCT (checked at Kimai 2.70.2).
        result += (
            "Note: for a search like 'name:~' or 'name:\"\"' Kimai counts a record once per meta field it "
            "has, so the total and the page count can be too high and later pages repeat records.\n\n"
        )

    result += await _filter_warnings(client, filters, user_scope, user_filter, fetched, names, all_records_of)

    if capped:
        result += (
            f"Not all records were used: the first {len(fetched)} were fetched (the limit is "
            f"{MAX_STATS_RESULTS}); narrow the filter, e.g. a shorter period.\n\n"
        )
    if lists_rows and more:
        # Without Kimai's headers a full page is all that is known.
        lead = "More records" if certain else "There may be more records"
        result += f"{lead}: use 'page' {requested_page + 1} for the next ones.\n\n"

    if filters.get("include_user_list"):
        result += "Available users:\n" + await _users_section(client, limit=10) + "\n"

    if calculate_stats:
        # Auto-enable year breakdown if time span > 1 year
        breakdown_by_year = filters.get("breakdown_by_year", False)
        if (
            not breakdown_by_year
            and begin_datetime is not None
            and end_datetime is not None
            and (end_datetime - begin_datetime).days > 365
        ):
            breakdown_by_year = True

        stats = TimesheetAnalytics.calculate_statistics(
            matched,
            breakdown_by_year=breakdown_by_year,
            period=(begin_datetime, end_datetime),
        )

        # Only the projects in this report, not every project of the instance.
        reported = stats.get("projects") or {}
        project_map = {pid: names.projects[pid].name for pid in reported if pid in names.projects}
        stats["project_names"] = project_map

        if stats_format == "json":
            result += "\n## Statistics (JSON):\n"
            result += json.dumps(stats, indent=2)
            result += "\n\n"
        else:
            result += "\n" + TimesheetAnalytics.format_statistics_report(stats, project_map)
            result += "\n\n"

        if not lists_rows:
            return [TextContent(type="text", text=result)]

    for ts in shown:
        result += _describe_timesheet(ts, names, show_user=show_user)

    return [TextContent(type="text", text=result)]


async def _filter_warnings(
    client: KimaiClient, filters: dict, user_scope: str, user_filter: str | None, fetched: list,
    names: RecordNames, all_records_of: Callable[[int], Awaitable[bool]],
) -> str:
    """Say when the records show that Kimai ignored a filter.

    A record that was not asked for is evidence on any page. "Only the
    caller's records" is not: the next page may hold someone else's, so that
    note asks ``all_records_of`` about the whole result.

    Kimai ignores user/users[] without view_other_timesheet, and skips IDs
    that do not exist; with nothing left it returns the caller's own records.
    It also drops project, activity and customer IDs that do not exist and
    then does not filter by that relation at all, so a wrong ID lists
    everything. Checked on everything fetched, before the meta match narrows
    it. (If the caller is among the requested users, nothing here can tell
    the difference.)
    """
    text = ""
    requested_users = (
        set(filters["users"]) if user_scope == "users"
        else {int(user_filter)} if user_scope == "specific" and str(user_filter).isdigit()
        else None
    )
    returned_users = {_ref(ts.user) for ts in fetched if ts.user is not None}
    foreign = sorted(returned_users - requested_users) if requested_users is not None else []
    if foreign:
        text += (
            f"Warning: Kimai returned records of user(s) {', '.join(map(str, foreign))}, which were not "
            "requested. It does so when the token lacks view_other_timesheet or the requested user IDs "
            "do not exist: it then ignores the user filter and returns the caller's own records.\n\n"
        )
    elif len(returned_users) == 1 and (user_scope == "all" or len(requested_users or ()) > 1):
        # Only one user's records for 'all', or for several requested users of
        # whom the caller is one: possibly only the caller's, the rest hidden.
        only = next(iter(returned_users))
        note = await own_records_note(client, only)
        if note and await all_records_of(only):
            text += note + "\n\n"
    elif not fetched and user_scope == "all":
        # An ignored user filter searches the caller's own records; when the
        # caller has none, the empty result reads as "nobody".
        text += (
            "Note: no records. Without view_other_timesheet Kimai ignores user=all and searches only your "
            "own records, so this may only mean that you have none for this filter.\n\n"
        )
    elif not fetched and requested_users:
        me = await best_effort(client.get_current_user())
        if me is not None and requested_users != {me.id}:
            text += (
                "Note: no records. Kimai ignores the user filter, and searches only your own records, when the "
                "token lacks view_other_timesheet or the requested user IDs do not exist; so this may only "
                "mean that you have none for this filter.\n\n"
            )

    relations = (
        ("project", "projects", lambda ts: _ref(ts.project)),
        ("activity", "activities", lambda ts: _ref(ts.activity)),
        ("customer", "customers", lambda ts: _customer_id(ts, names)),
    )
    for single, several, row_id in relations:
        asked = set(filters.get(several) or []) | ({filters[single]} if filters.get(single) is not None else set())
        if not asked:
            continue
        ids = [row_id(ts) for ts in fetched]
        stray = sorted({i for i in ids if i is not None} - asked)
        if None in ids:
            # Rows with IDs only, whose project the project listing did not
            # have (or the listing failed): their customer is unknown.
            text += (
                f"Note: {ids.count(None)} record(s) could not be checked against the {single} filter: "
                "their project is not in the project list this token can read.\n\n"
            )
        if stray:
            text += (
                f"Warning: Kimai returned records of {single} ID(s) {', '.join(map(str, stray))}, which were not "
                f"requested: it ignores {single} IDs that do not exist and then does not filter by {single} at all.\n\n"
            )
    return text


async def _handle_timesheet_get(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timesheet get action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for get action")
    
    ts = await client.get_timesheet(id)
    
    duration = worked_hours(ts) if ts.end else "Running"
    status = "Running" if not ts.end else "Stopped"
    
    result = f"Timesheet ID: {ts.id}\n"
    result += f"Project ID: {ts.project}\n"
    result += f"Activity ID: {ts.activity}\n"
    result += f"User ID: {ts.user if ts.user else 'Unknown'}\n"
    result += f"Status: {status}\n"
    
    result += f"Begin: {ts.begin.strftime('%Y-%m-%d %H:%M:%S')}\n"
    if ts.end:
        result += f"End: {ts.end.strftime('%Y-%m-%d %H:%M:%S')}\n"
        result += f"Duration: {duration:.2f} hours\n"
    
    result += f"Billable: {'Yes' if ts.billable else 'No'}\n"
    result += f"Exported: {'Yes' if ts.exported else 'No'}\n"
    
    if ts.description:
        result += f"Description: {quoted(ts.description)}\n"
    if ts.tags:
        result += f"Tags: {', '.join(value_text(tag) for tag in ts.tags)}\n"
    if ts.rate is None and ts.internal_rate is None and ts.fixed_rate is None and ts.hourly_rate is None:
        # Kimai 2.66+ strips all four rate fields per record when the token
        # lacks view_rate_own_timesheet / view_rate_other_timesheet.
        result += "Rates: not visible to this token (needs view_rate_own_timesheet resp. view_rate_other_timesheet; Kimai 2.66+ omits them per record)\n"
    # `is not None`, not truthiness: a visible 0.0 is a real value and must
    # stay distinguishable from a stripped field.
    if ts.rate is not None:
        result += f"Rate: {ts.rate}\n"
    if ts.internal_rate is not None:
        result += f"Internal Rate: {ts.internal_rate}\n"
    if ts.fixed_rate is not None:
        result += f"Fixed Rate: {ts.fixed_rate}\n"
    if ts.hourly_rate is not None:
        result += f"Hourly Rate: {ts.hourly_rate}\n"
    if ts.break_duration:
        result += f"Break: {ts.break_duration // 60} minutes\n"
    meta = _format_meta_fields(ts.meta_fields)
    if meta:
        result += f"Meta: {meta}\n"

    return [TextContent(type="text", text=result)]


async def _handle_timesheet_create(client: KimaiClient, data: dict) -> list[TextContent]:
    """Handle timesheet create action."""
    from datetime import datetime

    if not data.get("project") or not data.get("activity"):
        raise ToolError("Error: 'project' and 'activity' are required for create action")

    # Keep tags as string - model expects comma-separated string. Leave it
    # absent when the caller did not provide it: Kimai builds the API form from
    # the user's permissions and settings, so optional fields must not be
    # manufactured here.
    tags_str = data.get("tags")

    if "begin" in data:
        try:
            begin_datetime = datetime.fromisoformat(data["begin"])
        except ValueError:
            raise ToolError(
                f"Error: Invalid date format for field begin '{data['begin']}'. Use ISO format (YYYY-MM-DDTHH:MM:SS)")
    else:
        # Leave begin to Kimai ("the users current timestamp will be used").
        # In punch-in/out tracking mode the API form has no begin/end field
        # unless the token holds view_other_timesheet, so a manufactured
        # value fails the whole request as an extra field.
        begin_datetime = None

    end_datetime = None
    if "end" in data:
        try:
            end_datetime = datetime.fromisoformat(data["end"])
        except ValueError:
            raise ToolError(
                f"Error: Invalid date format for field end '{data['end']}'. Use ISO format (YYYY-MM-DDTHH:MM:SS)")
    
    form = TimesheetEditForm(
        project=data["project"],
        activity=data["activity"],
        begin=begin_datetime,
        end=end_datetime,
        description=data.get("description"),
        tags=tags_str,
        user=data.get("user"),
        # ``billable`` is only present in Kimai's form when the token has the
        # corresponding edit permission. Sending a default True made an
        # otherwise ordinary create fail with "extra fields" for ROLE_USER.
        billable=data.get("billable"),
        fixedRate=data.get("fixedRate"),
        hourlyRate=data.get("hourlyRate"),
        exported=data.get("exported"),
        break_duration=data.get("break")
    )

    ts = await client.create_timesheet(form)
    
    status = "Started (running)" if not ts.end else "Created"
    return [TextContent(
        type="text",
        text=f"{status} timesheet ID {ts.id} for project {ts.project} / activity {ts.activity}"
    )]


async def _handle_timesheet_update(client: KimaiClient, id: int | None, data: dict) -> list[TextContent]:
    """Handle timesheet update action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for update action")
    if not data:
        raise ToolError("Error: 'data' parameter is required for update action")
    
    # Parse tags if provided
    if "tags" in data:
        # Keep tags as string for model compatibility
        # data["tags"] is already a string from input
        pass
    
    form = TimesheetEditForm(**data)
    ts = await client.update_timesheet(id, form)
    
    return [TextContent(
        type="text",
        text=f"Updated timesheet ID {ts.id}"
    )]


async def _handle_timesheet_delete(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timesheet delete action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for delete action")
    
    await client.delete_timesheet(id)
    return [TextContent(type="text", text=f"Deleted timesheet ID {id}")]


async def _handle_timesheet_duplicate(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timesheet duplicate action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for duplicate action")
    
    ts = await client.duplicate_timesheet(id)
    return [TextContent(
        type="text",
        text=f"Duplicated timesheet ID {id} -> New timesheet ID {ts.id}"
    )]


async def _handle_timesheet_export_toggle(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timesheet export toggle action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for export_toggle action")
    
    ts = await client.toggle_timesheet_export(id)
    status = "exported" if ts.exported else "not exported"
    return [TextContent(
        type="text",
        text=f"Timesheet ID {id} marked as {status}"
    )]


async def _handle_timesheet_meta_update(client: KimaiClient, id: int | None, meta: list[dict]) -> list[TextContent]:
    """Handle timesheet meta update action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for meta_update action")
    if not meta:
        raise ToolError("Error: 'meta' parameter is required for meta_update action")
    
    # API accepts one meta field per request - iterate through each field
    updated_count = 0
    for field_data in meta:
        meta_field = MetaFieldForm(**field_data)
        await client.update_timesheet_meta(id, meta_field)
        updated_count += 1
    
    return [TextContent(
        type="text",
        text=f"Updated {updated_count} meta field(s) for timesheet ID {id}"
    )]


async def _handle_timesheet_user_guide(client: KimaiClient, show_users: bool) -> list[TextContent]:
    """Handle timesheet user guide action."""
    guide = """# Timesheet User Selection Guide

When using the timesheet tool with action='list', you can control which users' timesheets are shown:

## User Scope Options:

1. **'self'** (default) - Show only your own timesheets
   - No additional parameters needed
   - Uses the current authenticated user

2. **'all'** - Show timesheets from all users
   - Requires appropriate permissions
   - Useful for managers and administrators

3. **'specific'** - Show timesheets for a specific user
   - Requires the 'user' parameter with a user ID
   - Example: user_scope='specific', user='5'

## Examples:

1. Your own timesheets for a project:
   ```json
   {
     "action": "list",
     "filters": {
       "user_scope": "self",
       "project": 17
     }
   }
   ```

2. All users' timesheets for today:
   ```json
   {
     "action": "list",
     "filters": {
       "user_scope": "all",
       "begin": "2024-01-15T00:00:00",
       "end": "2024-01-15T23:59:59"
     }
   }
   ```

3. Specific user's timesheets:
   ```json
   {
     "action": "list",
     "filters": {
       "user_scope": "specific",
       "user": "5"
     }
   }
   ```
"""
    
    if show_users:
        guide += "\n## Available Users:\n\n" + await _users_section(client, limit=20)

    return [TextContent(type="text", text=guide)]


async def _users_section(client: KimaiClient, limit: int) -> str:
    """The users the token can see (teams first, then GET /users), one per line.

    Supplementary context for the listing and the guide: a failure is a line
    of text, except a 401, which propagates so the server rebuilds the
    session.
    """
    try:
        users = await resolve_accessible_users(client)
    except Exception as e:  # reported inline
        if isinstance(e, KimaiAPIError) and e.status_code == 401:
            raise
        if isinstance(e, KimaiAPIError) and e.status_code == 403:
            return (
                "Unable to list users (insufficient permissions). user_scope='specific' with a user ID still "
                "works where the token may see that user.\n"
            )
        return f"Unable to list users: {e!s}\n"
    lines = [
        f"  - ID: {user.id}, Username: {user.username}, Name: {user.alias or 'N/A'}"
        f"{'' if user.enabled else ' (inactive)'}"
        for user in users[:limit]
    ]
    if len(users) > limit:
        lines.append(f"  ... and {len(users) - limit} more users")
    return "\n".join(lines) + "\n"


# Timer action handlers
async def _handle_timer_start(client: KimaiClient, data: dict) -> list[TextContent]:
    """Handle timer start action."""
    if not data.get("project") or not data.get("activity"):
        raise ToolError("Error: 'project' and 'activity' are required in data for start action")
    
    # Keep tags as string - model expects comma-separated string. Do not add an
    # empty tags field when the caller omitted it.
    tags_str = data.get("tags")
    
    form = TimesheetEditForm(
        project=data["project"],
        activity=data["activity"],
        # No begin: Kimai starts the record at the current timestamp itself,
        # and punch-in/out mode has no begin field for plain users.
        description=data.get("description"),
        tags=tags_str
    )
    
    ts = await client.create_timesheet(form)
    
    return [TextContent(
        type="text",
        text=f"Started timer ID {ts.id} for project {ts.project} / activity {ts.activity}"
    )]


async def _handle_timer_stop(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timer stop action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for stop action")
    
    ts = await client.stop_timesheet(id)
    
    duration = worked_hours(ts)
    return [TextContent(
        type="text",
        text=f"Stopped timer ID {ts.id}. Duration: {duration:.2f} hours"
    )]


async def _handle_timer_restart(client: KimaiClient, id: int | None) -> list[TextContent]:
    """Handle timer restart action."""
    if not id:
        raise ToolError("Error: 'id' parameter is required for restart action")
    
    ts = await client.restart_timesheet(id)
    
    return [TextContent(
        type="text",
        text=f"Restarted timer ID {ts.id} for project {ts.project} / activity {ts.activity}"
    )]


def _ref(value):
    """The ID of a relation, whether the row has it as an ID or as an object (Expanded)."""
    return getattr(value, "id", value)


def _customer_id(ts, names: RecordNames) -> int | None:
    """The customer of a row: from the Expanded project, else from the project listing."""
    if not isinstance(ts.project, int):
        return ts.project.customer.id if ts.project.customer else None
    project = names.projects.get(ts.project)
    return project.customer if project else None


def _work_label(ts, names: RecordNames) -> str:
    """``Customer / Project (#id) / Activity (#id)``, or the IDs where no name is known."""
    if isinstance(ts.project, int):
        known = names.projects.get(ts.project)
        project = f"project #{ts.project}"
        if known:
            project = f"{known.name} (#{known.id})"
            if known.parent_title:  # the customer's name
                project = f"{known.parent_title} / {project}"
    else:
        project = f"{ts.project.name} (#{ts.project.id})"
        if ts.project.customer:
            project = f"{ts.project.customer.name} / {project}"
    if isinstance(ts.activity, int):
        name = names.activities.get(ts.activity)
        activity = f"{name} (#{ts.activity})" if name else f"activity #{ts.activity}"
    else:
        activity = f"{ts.activity.name} (#{ts.activity.id})"
    return f"{project} / {activity}"


def _user_label(user, names: RecordNames) -> str:
    if isinstance(user, int):
        name = names.users.get(user)
        return f"{name} (#{user})" if name else f"user #{user}"
    return f"{user.alias or user.username} (#{user.id})"


_NO_NAMES = RecordNames()  # Expanded rows name themselves


def _describe_timesheet(ts, names: RecordNames = _NO_NAMES, show_user: bool = True) -> str:
    """One record of a listing: a line with when, how long, what, who and why,
    then a line each only for what is present or deviates.

    The Expanded rows (list, active, recent, favorites) name their relations;
    the ``TimesheetEntity`` rows behind statistics and the meta filter are
    named from ``names`` where the lookups found them, else shown by ID.
    "not billable" and "exported" are printed only when they apply. Rates
    are printed only where Kimai sent them: since 2.66 it strips them per
    record unless the token may view rates.
    """
    begin = ts.begin
    if ts.end is None:
        # tzinfo=None mirrors a naive begin, so both sides stay comparable.
        elapsed = (datetime.now(begin.tzinfo) - begin).total_seconds() / 3600
        when = f"{begin:%Y-%m-%d %H:%M}-now (running, {elapsed:.2f} h so far)"
    else:
        end = f"{ts.end:%H:%M}" if ts.end.date() == begin.date() else f"{ts.end:%Y-%m-%d %H:%M}"
        when = f"{begin:%Y-%m-%d %H:%M}-{end}, {worked_hours(ts):.2f} h"
    if ts.break_duration:
        when += f" (break {ts.break_duration // 60} min)"
    line = f"#{ts.id} {when}, {_work_label(ts, names)}"
    if show_user and ts.user is not None:
        line += f", {_user_label(ts.user, names)}"
    if ts.description:
        line += " - " + one_line(ts.description)
    lines = [line]

    details = ["not billable"] if not ts.billable else []
    if ts.exported:
        details.append("exported")
    details += [
        f"{label} {value}"
        for label, value in (
            ("rate", ts.rate),
            ("internal rate", ts.internal_rate),
            ("fixed rate", ts.fixed_rate),
            ("hourly rate", ts.hourly_rate),
        )
        if value is not None
    ]
    if details:
        lines.append("  " + ", ".join(details))

    extras = [f"tags: {', '.join(value_text(tag) for tag in ts.tags)}"] if ts.tags else []
    meta = _format_meta_fields(ts.meta_fields)
    if meta:
        extras.append(f"meta: {meta}")
    if extras:
        lines.append("  " + "; ".join(extras))
    # Backstop: the models hand over single-line names and the values above are
    # quoted, so no part brings a line break. A field added later without that
    # care is still kept from splitting the record (the indent stays).
    return "\n".join(line[: len(line) - len(line.lstrip())] + one_line(line.lstrip()) for line in lines) + "\n"


async def _handle_timer_active(client: KimaiClient) -> list[TextContent]:
    """Handle timer active action."""
    timesheets = await client.get_active_timesheets()
    
    if not timesheets:
        return [TextContent(type="text", text="No active timers running")]
    
    result = f"Found {len(timesheets)} active timer(s):\n\n"
    
    for ts in timesheets:
        result += _describe_timesheet(ts, show_user=False)

    return [TextContent(type="text", text=result)]


async def _handle_timer_favorites(client: KimaiClient) -> list[TextContent]:
    """Handle timer favorites action (Kimai 2.66+)."""
    timesheets = await client.get_favorite_timesheets()

    if not timesheets:
        return [TextContent(
            type="text",
            text="No favorite timesheets. Mark one of your own records with timer action=favorite id=<timesheet id> (Kimai 2.66+).",
        )]

    result = f"Found {len(timesheets)} favorite timesheet(s). Start one with timer action=restart id=<ID>.\n\n"

    for ts in timesheets:
        result += _describe_timesheet(ts, show_user=False)

    return [TextContent(type="text", text=result)]


async def _handle_timer_favorite(client: KimaiClient, id: int | None, add: bool) -> list[TextContent]:
    """Handle timer favorite / unfavorite actions (Kimai 2.66+)."""
    action = "favorite" if add else "unfavorite"
    if not id:
        raise ToolError(f"Error: 'id' parameter is required for {action} action")

    if add:
        await client.add_favorite_timesheet(id)
        text = f"Timesheet ID {id} added to favorites"
    else:
        await client.remove_favorite_timesheet(id)
        text = f"Timesheet ID {id} removed from favorites"

    return [TextContent(type="text", text=text)]


async def _handle_timer_recent(client: KimaiClient, size: int, begin: str | None) -> list[TextContent]:
    """Handle timer recent action."""
    
    begin_datetime = parse_local_datetime(begin, "begin") if begin else None

    # Kimai's "recent activities": the latest record of each customer/project/
    # activity combination (Expanded, so with names), which is what a restart
    # needs. Listing the latest records is what `timesheet action=list` is for.
    timesheets = await client.get_recent_timesheets(begin=begin_datetime, size=size)

    result = (
        f"Recent {len(timesheets)} activities (latest record per customer/project/activity). "
        "Restart one with timer action=restart id=<ID>.\n\n"
    )

    for ts in timesheets:
        result += _describe_timesheet(ts, show_user=False)

    return [TextContent(type="text", text=result)]


# Batch operations

async def _handle_batch_delete(client: KimaiClient, ids: list[int]) -> list[TextContent]:
    """Batch delete multiple timesheets."""
    if not ids:
        raise ToolError("Error: 'ids' parameter is required for batch_delete action")

    async def delete_one(id: int) -> int:
        await client.delete_timesheet(id)
        return id

    success, failed = await execute_batch(ids, delete_one)
    result = format_batch_result("Delete", success, failed, "timesheets")
    return [TextContent(type="text", text=result)]


async def _handle_batch_export(client: KimaiClient, ids: list[int]) -> list[TextContent]:
    """Batch mark multiple timesheets as exported."""
    if not ids:
        raise ToolError("Error: 'ids' parameter is required for batch_export action")

    # PATCH /timesheets/{id}/export *toggles* the flag (setExported(!isExported())),
    # so a record that is exported already must be left alone, or "mark as
    # exported" would un-export it. (execute_batch drops repeated ids, which
    # would otherwise both read "not exported" and toggle twice.)
    async def export_one(id: int) -> bool:
        if (await client.get_timesheet(id)).exported:
            return False
        await client.toggle_timesheet_export(id)
        return True

    success, failed = await execute_batch(ids, export_one)
    newly = [changed for changed in success if changed]
    result = format_batch_result("Export", newly, failed, "timesheets")
    if len(newly) < len(success):
        result += f"- Already exported, left unchanged: {len(success) - len(newly)}\n"
    return [TextContent(type="text", text=result)]
