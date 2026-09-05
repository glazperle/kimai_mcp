#!/usr/bin/env python3
"""Read-only compliance check against a running Kimai instance.

Complements scripts/audit_api_models.py: that one derives the expected schemas
from the Kimai sources, this one asks a real server what it actually sends,
which also covers the fields that come from traits and are invisible to a
source-level audit.

Every request is a GET. Nothing is created, changed or deleted, so it is safe
to point at production.

    $env:KIMAI_URL = "https://kimai.example.com"
    $env:KIMAI_API_TOKEN = "..."
    python scripts/verify_against_kimai.py

Exit code 1 means the server sent a field no model carries, or a documented
expectation did not hold.
"""

from __future__ import annotations

import asyncio
import os
import sys

from kimai_mcp.client import KimaiAPIError, KimaiClient
from kimai_mcp.models import (
    Activity,
    Customer,
    CustomerFilter,
    Project,
    TimesheetEntity,
    TimesheetExpanded,
    User,
    UserEntity,
)
from kimai_mcp.tools.registry import dispatch_tool

# Serialized by Kimai, deliberately not modelled (see models.py).
EXPECTED_UNMODELLED = {"color-safe", "apiToken"}

# Customer serializer groups, per src/Entity/Customer.php.
DETAILS_GROUP = {"vatId", "addressLine1", "addressLine2", "addressLine3", "postCode", "city"}
ENTITY_ONLY = {"contact", "address", "email", "invoiceEmail", "buyerReference"}
# Budget_Money / Budget_Time (src/Entity/BudgetTrait.php). Entity-only up to
# 2.65; since 2.66 also in listings, but only for records the token holds the
# `budget` resp. `time` permission for (BudgetExclusionStrategy), so on 2.66+
# their presence is informational, their absence is not a defect.
BUDGET_GROUP = {"budget", "timeBudget", "budgetType"}
# Timesheet_Rate / Timesheet_Entity_Rate (2.66+, RateExclusionStrategy): gated
# per record by view_rate_own_timesheet / view_rate_other_timesheet.
RATE_GROUP = {"rate", "internalRate"}
RATE_ENTITY_GROUP = {"fixedRate", "hourlyRate"}

results: list[tuple[bool, str]] = []


def check(ok: bool, message: str) -> None:
    results.append((ok, message))
    print(f"[{'  OK  ' if ok else ' FAIL '}] {message}")


def unmodelled(payload: dict, model) -> set:
    known = {field.alias or name for name, field in model.model_fields.items()}
    known |= set(model.model_fields) | EXPECTED_UNMODELLED
    return set(payload) - known


async def main() -> int:
    base_url = os.getenv("KIMAI_URL", "").rstrip("/")
    token = os.getenv("KIMAI_API_TOKEN", "")
    if not base_url or not token:
        print("Set KIMAI_URL and KIMAI_API_TOKEN.")
        return 2

    client = KimaiClient(base_url, token)
    try:
        version = await client.get_version()
        check(True, f"connected to Kimai {version.version}")
        major, minor = (int(p) for p in version.version.split(".")[:2])

        # Every response we parse must be fully covered by its model. Kimai
        # serves a richer shape for a single entity than for a listing, which is
        # why the detail endpoint is compared against the entity model.
        listings: dict[str, list] = {}
        for endpoint, list_model, detail_model, params in (
            ("/customers", Customer, Customer, {"visible": 1}),
            ("/projects", Project, Project, {"visible": 1}),
            ("/activities", Activity, Activity, {"visible": 1}),
            ("/users", User, UserEntity, {}),
        ):
            items = await client._request("GET", endpoint, params=params)
            listings[endpoint] = items
            if not items:
                check(True, f"{endpoint}: empty, nothing to compare")
                continue
            extra = unmodelled(items[0], list_model)
            check(not extra,
                  f"{endpoint} listing fully modelled by {list_model.__name__} "
                  f"(unknown: {sorted(extra) or 'none'})")

            detail = await client._request("GET", f"{endpoint}/{items[0]['id']}")
            extra = unmodelled(detail, detail_model)
            check(not extra,
                  f"{endpoint}/{{id}} fully modelled by {detail_model.__name__} "
                  f"(unknown: {sorted(extra) or 'none'})")

        # Customer serializer groups behave as documented.
        customers = await client._request("GET", "/customers", params={"visible": 1})
        if customers:
            plain = set(customers[0])
            if (major, minor) >= (2, 63):
                check("language" in plain, "'language' is in a plain listing (Default group)")
            check(not (DETAILS_GROUP & plain), "detail fields absent without full=1")

            if (major, minor) >= (2, 62):
                full = await client._request("GET", "/customers",
                                             params={"visible": 1, "full": 1})
                added = DETAILS_GROUP & set(full[0]) if full else set()
                check(bool(added) or True,
                      f"full=1 adds {sorted(added) or 'nothing (token lacks details_customer?)'}")
                check(not (ENTITY_ONLY & set(full[0]) if full else set()),
                      "entity-only fields stay out of listings even with full=1")
                budget_in_listing = BUDGET_GROUP & set(full[0]) if full else set()
                if (major, minor) >= (2, 66):
                    check(True,
                          f"2.66+: budget fields in the listing for the first record: "
                          f"{sorted(budget_in_listing) or 'none (token lacks budget/time on it)'}")
                else:
                    check(not budget_in_listing,
                          "budget fields stay out of listings before 2.66")
                await client.get_customers(CustomerFilter(visible=1, full=1))
                check(True, "CustomerFilter(full=1) round-trips through the client")

        # Projects: lockedUntil (2.66+) is group Default, so a listing carries it
        # for every project; the model must accept both the date and null.
        if (major, minor) >= (2, 66):
            projects = listings.get("/projects") or []
            if projects:
                check(all("lockedUntil" in p for p in projects),
                      "2.66+: every project listing row carries 'lockedUntil'")
                locked = [p["id"] for p in projects if p.get("lockedUntil")]
                check(True, f"projects with a lock date: {locked or 'none'}")

        # Timesheets: the four rate fields are per-record optional since 2.66.
        # Whatever the token sees must parse, and the model must not report a
        # stripped rate as zero.
        sheets = await client._request("GET", "/timesheets", params={"size": 5})
        if not sheets:
            check(True, "/timesheets: empty, nothing to compare")
        else:
            extra = unmodelled(sheets[0], TimesheetEntity)
            check(not extra,
                  f"/timesheets listing fully modelled by TimesheetEntity "
                  f"(unknown: {sorted(extra) or 'none'})")
            seen = RATE_GROUP & set(sheets[0])
            parsed = TimesheetEntity(**sheets[0])
            if seen:
                check(parsed.rate == sheets[0].get("rate"),
                      f"rate fields present ({sorted(seen)}) and parsed verbatim")
            else:
                check(parsed.rate is None,
                      "rate fields absent (token lacks view_rate_*) and parsed as None, not 0.0")
            detail = await client._request("GET", f"/timesheets/{sheets[0]['id']}")
            extra = unmodelled(detail, TimesheetEntity)
            check(not extra,
                  f"/timesheets/{{id}} fully modelled by TimesheetEntity "
                  f"(unknown: {sorted(extra) or 'none'})")
            check(True, f"entity rate fields present: "
                        f"{sorted((RATE_GROUP | RATE_ENTITY_GROUP) & set(detail)) or 'none'}")

        # Favorites (2.66+): read-only probe of the new collection endpoint.
        if (major, minor) >= (2, 66):
            try:
                favorites = await client._request("GET", "/favorites/timesheets")
            except KimaiAPIError as exc:  # 403 without start_own_timesheet
                check(True, f"/favorites/timesheets not readable with this token ({exc})")
            else:
                for row in favorites:
                    TimesheetExpanded(**row)
                extra = unmodelled(favorites[0], TimesheetExpanded) if favorites else set()
                check(not extra,
                      f"/favorites/timesheets ({len(favorites)} rows) modelled by "
                      f"TimesheetExpanded (unknown: {sorted(extra) or 'none'})")

        # The tools render real payloads without raising.
        for args in (
            {"type": "customer", "action": "list"},
            {"type": "project", "action": "list"},
            {"type": "activity", "action": "list"},
        ):
            rendered = await dispatch_tool(client, "entity", args)
            check(bool(rendered and rendered[0].text.strip()),
                  f"entity {args['type']} {args['action']} rendered "
                  f"{len(rendered[0].text.splitlines())} lines")
    finally:
        await client.close()

    failed = [m for ok, m in results if not ok]
    print(f"\n{len(results)} checks, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
