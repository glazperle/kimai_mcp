"""Retries, the one-page listing with names, and the filter notes that need a lookup.

Each test names what the tool did before: a 503 from a restarting proxy failed
the call, a listing without 'page' fetched every page and ignored 'size', rows
showed IDs only, and an unknown customer ID or an ignored user filter on an
empty result went unnoticed.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import kimai_mcp.client as client_module
from kimai_mcp.client import KimaiAPIError, KimaiClient, TimesheetPage
from kimai_mcp.models import (
    Project,
    TimesheetEntity,
    TimesheetExpanded,
    TimesheetFilter,
    UserEntity,
)
from kimai_mcp.tools import timesheet_consolidated as ts
from kimai_mcp.tools.registry import dispatch_tool

# --- retries -------------------------------------------------------------------


@pytest.fixture
def slept(monkeypatch) -> list[float]:
    """The retry delays, recorded instead of slept."""
    delays: list[float] = []

    async def sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(client_module, "asyncio", SimpleNamespace(sleep=sleep))
    return delays


def _transport_client(handler) -> KimaiClient:
    # ssl_verify=False: loading the CA bundle costs half a second per client.
    client = KimaiClient(base_url="https://kimai.example.com", api_token="token", ssl_verify=False)
    client._client = httpx.AsyncClient(
        base_url="https://kimai.example.com/api", transport=httpx.MockTransport(handler)
    )
    return client


def _answers(*statuses, headers=None):
    calls = []

    def handler(request):
        calls.append(request.method)
        status = statuses[min(len(calls), len(statuses)) - 1]
        return httpx.Response(status, json={"message": "x"} if status >= 400 else {"version": "2.70.2"},
                              headers=headers or {})

    return handler, calls


@pytest.mark.asyncio
async def test_a_read_is_retried_on_a_gateway_error(slept):
    handler, calls = _answers(503, 502, 200)
    client = _transport_client(handler)

    data = await client._request("GET", "/version")

    assert data == {"version": "2.70.2"}
    assert len(calls) == 3
    assert slept == list(KimaiClient.RETRY_DELAYS)


@pytest.mark.asyncio
async def test_retry_after_is_honoured(slept):
    handler, _calls = _answers(429, 429, 200, headers={"Retry-After": "1"})
    client = _transport_client(handler)

    await client._request("GET", "/version")

    assert slept == [1.0, 1.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds", ["60", "3600", "nan", "inf"])
async def test_a_long_retry_after_fails_at_once(slept, seconds):
    """Waiting 10 s twice for a server that said 60 s only repeats the refusal,
    and runs past the MCP client's own timeout."""
    handler, calls = _answers(429, 200, headers={"Retry-After": seconds})
    client = _transport_client(handler)

    with pytest.raises(KimaiAPIError) as raised:
        await client._request("GET", "/version")

    assert raised.value.status_code == 429
    assert (len(calls), slept) == (1, [])


@pytest.mark.asyncio
async def test_a_gateway_timeout_is_not_retried(slept):
    """504: the gateway gave up waiting for a slow Kimai, which would get the
    same request again."""
    handler, calls = _answers(504, 200)
    client = _transport_client(handler)

    with pytest.raises(KimaiAPIError):
        await client._request("GET", "/version")

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_the_last_answer_is_raised_when_retries_run_out(slept):
    handler, calls = _answers(503)
    client = _transport_client(handler)

    with pytest.raises(KimaiAPIError) as raised:
        await client._request("GET", "/version")

    assert raised.value.status_code == 503
    assert len(calls) == len(KimaiClient.RETRY_DELAYS) + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
async def test_a_write_is_never_retried(method, slept):
    """A write that got a 502 may still have reached Kimai: repeating it could
    create a record twice or toggle a flag back."""
    handler, calls = _answers(502, 200)
    client = _transport_client(handler)

    with pytest.raises(KimaiAPIError):
        await client._request(method, "/timesheets/1/export")

    assert calls == [method]
    assert slept == []


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ReadError, httpx.RemoteProtocolError])
async def test_a_dropped_connection_is_retried_for_reads(slept, error):
    """A reset, or a keep-alive connection the server had already closed."""
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise error("connection reset")
        return httpx.Response(200, json=[])

    client = _transport_client(handler)

    assert await client._request("GET", "/timesheets") == []
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
async def test_an_unreachable_server_is_not_retried(slept, error):
    """A refused connection, an unknown host or a connect timeout fails the same
    way again; each retry cost up to the full timeout (92 s instead of 30 s)."""
    calls = []

    def handler(request):
        calls.append(1)
        raise error("unreachable")

    client = _transport_client(handler)

    with pytest.raises(KimaiAPIError):
        await client._request("GET", "/timesheets")

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_read_timeout_is_not_retried(slept):
    """A server too slow for the timeout would only get the same load again."""
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("timed out")

    client = _transport_client(handler)

    with pytest.raises(KimaiAPIError):
        await client._request("GET", "/timesheets")

    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("offset", "retried"), [(5, True), (3600, False)])
async def test_a_retry_after_date_is_honoured(slept, offset, retried):
    """RFC 9110 allows an HTTP date; it was read as 'unparsable' and retried at once."""
    from email.utils import format_datetime

    when = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=offset), usegmt=True)
    handler, calls = _answers(503, 200, headers={"Retry-After": when})
    client = _transport_client(handler)

    if retried:
        await client._request("GET", "/version")
        assert len(slept) == 1
        assert 3 <= slept[0] <= 5
    else:
        with pytest.raises(KimaiAPIError):
            await client._request("GET", "/version")
        assert (len(calls), slept) == (1, [])


@pytest.mark.asyncio
async def test_a_client_error_is_not_retried(slept):
    handler, calls = _answers(404, 200)
    client = _transport_client(handler)

    with pytest.raises(KimaiAPIError):
        await client._request("GET", "/timesheets/1")

    assert len(calls) == 1


# --- one page with Kimai's headers ---------------------------------------------

_EXPANDED_ROW = {
    "id": 5, "begin": "2026-09-01T09:00:00+0200", "end": "2026-09-01T10:00:00+0200", "duration": 3600,
    "tags": [], "user": {"id": 3, "username": "alice"},
    "project": {"id": 2, "name": "Relaunch", "customer": {"id": 9, "name": "Acme"}},
    "activity": {"id": 1, "name": "Meetings"},
}


@pytest.mark.asyncio
async def test_a_page_carries_kimais_totals_and_expanded_rows():
    seen = []

    def handler(request):
        seen.append(request.url.params)
        return httpx.Response(200, json=[_EXPANDED_ROW], headers={"X-Total-Count": "51", "X-Total-Pages": "11"})

    client = _transport_client(handler)

    page = await client.get_timesheet_page(TimesheetFilter(user="all", page=2, size=5, full="true"))

    assert (page.total, page.total_pages, page.page, page.has_more) == (51, 11, 2, True)
    assert isinstance(page.rows[0], TimesheetExpanded)
    assert (seen[0]["page"], seen[0]["size"], seen[0]["full"]) == ("2", "5", "true")


def test_without_headers_a_full_page_may_have_more():
    assert TimesheetPage(rows=[1, 2], page=1, size=2).has_more
    assert not TimesheetPage(rows=[1], page=1, size=2).has_more
    assert not TimesheetPage(rows=[1, 2], page=3, size=2, total=6, total_pages=3).has_more


@pytest.mark.asyncio
async def test_a_page_read_does_not_page_on():
    """A full page with more to come: one request, the rest is the caller's 'page'."""
    calls = []

    def handler(request):
        calls.append(request.url.params["page"])
        return httpx.Response(200, json=[_EXPANDED_ROW], headers={"X-Total-Count": "9", "X-Total-Pages": "9"})

    client = _transport_client(handler)

    page = await client.get_timesheet_page(TimesheetFilter(user="all", size=1, full="true"))

    assert calls == ["1"]
    assert page.has_more


# --- rows ------------------------------------------------------------------------


def test_a_row_names_what_and_who_on_one_line():
    row = TimesheetExpanded(**_EXPANDED_ROW, description="Sprint planning\nand review")

    text = ts._describe_timesheet(row)

    assert text == (
        "#5 2026-09-01 09:00-10:00, 1.00 h, Acme / Relaunch (#2) / Meetings (#1), alice (#3)"
        " - Sprint planning | and review\n"
    )


def test_a_row_shows_only_flags_that_deviate():
    row = TimesheetEntity(
        id=7, project=2, activity=1, user=3, begin="2026-09-01T22:00:00+0200", end="2026-09-02T01:00:00+0200",
        duration=9000, billable=False, exported=True, rate=150.0, tags=["a", "b"],
        metaFields=[{"name": "ticket", "value": "CA-1"}], **{"break": 1800},
    )

    text = ts._describe_timesheet(row)

    assert text == (
        "#7 2026-09-01 22:00-2026-09-02 01:00, 2.50 h (break 30 min), project #2 / activity #1, user #3\n"
        "  not billable, exported, rate 150.0\n"
        "  tags: a, b; meta: ticket=CA-1\n"
    )


def test_fifty_rows_cost_a_third_less_than_before():
    """The former layout spent nine lines per record, IDs only."""
    row = TimesheetExpanded(**_EXPANDED_ROW, description="Sprint planning", rate=80.0)
    before = (
        "ID: 5 - Project: Acme / Relaunch / Activity: Meetings\n  User: alice (ID: 3)\n  Duration: 1.00 hours\n"
        "  Begin: 2026-09-01 09:00\n  End: 2026-09-01 10:00\n  Billable: Yes | Exported: No\n  Rate: 80.0\n"
        "  Description: Sprint planning\n\n"
    )

    assert len(ts._describe_timesheet(row)) * 3 <= len(before) * 2


# --- notes that need a lookup ------------------------------------------------------


def _listing_client(rows: list) -> AsyncMock:
    client = AsyncMock(spec=KimaiClient)
    client.get_current_user.return_value = UserEntity(id=1, username="me", enabled=True)
    client.get_timesheet_page.return_value = TimesheetPage(rows=rows, page=1, size=50, total=len(rows))
    client.get_timesheets.return_value = (rows, True)
    client.get_projects.return_value = []
    client.get_activities.return_value = []
    client.get_users.return_value = []
    return client


@pytest.mark.asyncio
async def test_records_of_an_unrequested_customer_are_flagged():
    """Kimai drops customer IDs that do not exist and then does not filter by customer."""
    client = _listing_client([TimesheetExpanded(**_EXPANDED_ROW)])  # customer 9

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {"customer": 99999}}))[0].text

    assert "Warning: Kimai returned records of customer ID(s) 9" in text


@pytest.mark.asyncio
async def test_the_customer_check_uses_the_project_listing_for_rows_with_ids():
    row = TimesheetEntity(id=1, project=2, activity=1, user=1, begin="2026-09-01T09:00:00+0200",
                          end="2026-09-01T10:00:00+0200", duration=3600)
    client = _listing_client([row])
    client.get_projects.return_value = [Project(id=2, name="Relaunch", customer=9, parentTitle="Acme")]

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {
        "customers": [4], "calculate_stats": True, "stats_format": "detailed",
    }}))[0].text

    assert "Warning: Kimai returned records of customer ID(s) 9" in text
    assert "Acme / Relaunch (#2) / activity #1" in text


@pytest.mark.asyncio
async def test_an_empty_result_for_another_user_says_the_filter_may_be_ignored():
    """Without view_other_timesheet Kimai returns the caller's records instead;
    a caller without any made that look like "user 7 has none"."""
    client = _listing_client([])

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {
        "user_scope": "specific", "user": "7",
    }}))[0].text

    assert "Kimai ignores the user filter, and searches only your own records" in text
    assert "requested user IDs do not exist" in text


@pytest.mark.asyncio
async def test_an_empty_result_for_the_caller_has_no_such_note():
    client = _listing_client([])

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {
        "user_scope": "specific", "user": "1",
    }}))[0].text

    assert "view_other_timesheet" not in text


@pytest.mark.asyncio
async def test_project_view_403_is_remembered():
    """GET /projects/{id} is a 403 for every project of a default user; asking
    again on every analysis was a wasted round trip."""
    client = AsyncMock(spec=KimaiClient)
    client.get_project.side_effect = KimaiAPIError("Forbidden", 403)
    client.get_projects.return_value = [Project(id=7, name="Relaunch")]
    client.get_activities.return_value = []
    client.get_users.return_value = []
    client.get_current_user.return_value = UserEntity(id=1, username="me", enabled=True)
    record = TimesheetEntity(id=1, project=7, activity=2, user=1, duration=3600,
                             begin=datetime(2024, 5, 1, 9, tzinfo=timezone.utc),
                             end=datetime(2024, 5, 1, 10, tzinfo=timezone.utc))
    client.get_timesheets.return_value = ([record], True)
    arguments = {"project_id": 7, "begin": "2024-01-01T00:00:00", "end": "2024-12-31T23:59:59"}

    client.denied_project_views = set()

    await dispatch_tool(client, "analyze_project_team", arguments)
    await dispatch_tool(client, "analyze_project_team", arguments)

    assert client.get_project.await_count == 1
    assert client.denied_project_views == {7}


@pytest.mark.asyncio
async def test_a_refused_project_does_not_stop_views_of_others():
    """A team lead may open its teams' projects but not one without teams; that
    403 must not route its own projects to the full listing."""
    client = AsyncMock(spec=KimaiClient)
    client.denied_project_views = {99}
    client.get_project.return_value = Project(id=7, name="Relaunch")
    client.get_activities.return_value = []
    client.get_users.return_value = []
    client.get_current_user.return_value = UserEntity(id=1, username="me", enabled=True)
    client.get_timesheets.return_value = ([], True)

    await dispatch_tool(client, "analyze_project_team", {
        "project_id": 7, "begin": "2024-01-01T00:00:00", "end": "2024-12-31T23:59:59",
    })

    client.get_project.assert_awaited_once_with(7)
    client.get_projects.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_users_403_is_remembered():
    """view_user is role-wide: the second listing does not ask GET /users again."""
    row = TimesheetEntity(id=1, project=2, activity=1, user=5, begin="2026-09-01T09:00:00+0200",
                          end="2026-09-01T10:00:00+0200", duration=3600,
                          metaFields=[{"name": "ticket", "value": "CA-1"}])
    client = _listing_client([row])
    client.users_list_denied = False
    client.get_users.side_effect = KimaiAPIError("Access denied", 403)
    arguments = {"action": "list", "filters": {"user_scope": "all", "meta": {"name": "ticket", "value": "CA-1"}}}

    await dispatch_tool(client, "timesheet", arguments)
    await dispatch_tool(client, "timesheet", arguments)

    assert client.get_users.await_count == 1
    assert client.users_list_denied is True


@pytest.mark.asyncio
async def test_activities_are_looked_up_for_the_shown_projects_only():
    row = TimesheetEntity(id=1, project=2, activity=1, user=1, begin="2026-09-01T09:00:00+0200",
                          end="2026-09-01T10:00:00+0200", duration=3600,
                          metaFields=[{"name": "ticket", "value": "CA-1"}])
    client = _listing_client([row])

    await dispatch_tool(client, "timesheet", {"action": "list", "filters": {"meta": {"name": "ticket", "value": "CA-1"}}})

    assert client.get_activities.await_args.args[0].projects == [2]


@pytest.mark.asyncio
async def test_records_whose_customer_cannot_be_told_are_counted():
    """A failed project listing used to drop the customer check without a word."""
    row = TimesheetEntity(id=1, project=2, activity=1, user=1, begin="2026-09-01T09:00:00+0200",
                          end="2026-09-01T10:00:00+0200", duration=3600)
    client = _listing_client([row])
    client.get_projects.side_effect = KimaiAPIError("Internal Server Error", 500)

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {
        "customer": 99999, "calculate_stats": True,
    }}))[0].text

    assert "1 record(s) could not be checked against the customer filter" in text


@pytest.mark.asyncio
async def test_a_capped_result_says_at_least():
    row = TimesheetEntity(id=1, project=2, activity=1, user=1, begin="2026-09-01T09:00:00+0200",
                          end="2026-09-01T10:00:00+0200", duration=3600)
    client = _listing_client([row])
    client.get_timesheets.return_value = ([row], False)

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {"calculate_stats": True}}))[0].text

    assert text.startswith("Found at least 1 timesheets")
    assert "Not all records were used" in text


@pytest.mark.asyncio
async def test_a_meta_search_with_tilde_warns_about_kimais_count():
    client = _listing_client([])

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {"term": "ticket:~"}}))[0].text

    assert "Kimai counts a record once per meta field" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {"type": "user", "action": "create", "data": {"username": "ana", "email": "a@example.com",
                                                   "language": "de", "locale": "de", "timezone": "Europe/Berlin",
                                                   "plainPassword": "S3cr3t-PW!", "plainApiToken": "tok-123456"}},
])
async def test_a_failed_write_never_logs_its_body(caplog, arguments):
    """The 4xx log line carried the request body, a new user's password included."""
    def handler(request):
        return httpx.Response(400, json={"code": 400, "message": "The username is already used."})

    client = _transport_client(handler)

    with caplog.at_level("INFO"), pytest.raises(KimaiAPIError):
        await dispatch_tool(client, "entity", arguments)

    assert "S3cr3t-PW!" not in caplog.text
    assert "tok-123456" not in caplog.text


def test_the_server_log_masks_secrets():
    from kimai_mcp.server import redact_secrets

    masked = redact_secrets({"type": "user", "data": {"plainPassword": "pw", "plainApiToken": "t", "email": "e"}})

    assert masked == {"type": "user", "data": {"plainPassword": "***", "plainApiToken": "***", "email": "e"}}


@pytest.mark.asyncio
@pytest.mark.parametrize(("own_total", "noted"), [(40, True), (39, False)])
async def test_only_own_records_on_one_page_of_many_asks_kimai_for_the_rest(own_total, noted):
    """The next page may hold other users' records. One record of the same
    filter for the caller alone tells: the same total means nobody else has
    any. Without it a ROLE_USER's 120 own records read as everyone's."""
    row = TimesheetExpanded(**{**_EXPANDED_ROW, "user": {"id": 1, "username": "me"}})
    client = _listing_client([row])
    client.get_timesheet_page.side_effect = [
        TimesheetPage(rows=[row], page=1, size=1, total=40, total_pages=40),
        TimesheetPage(rows=[row], page=1, size=1, total=own_total, total_pages=own_total),
    ]

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {
        "user_scope": "all", "size": 1, "project": 2,
    }}))[0].text

    probe = client.get_timesheet_page.await_args.args[0]
    assert (probe.user, probe.users, probe.size, probe.project) == ("1", None, 1, 2)
    assert ("every record returned is your own" in text) is noted


@pytest.mark.asyncio
async def test_an_empty_result_for_all_users_says_the_filter_may_be_ignored():
    """Without view_other_timesheet user=all searches the caller's records only;
    a bare 'Found 0' reads as "nobody worked on it"."""
    client = _listing_client([])

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {
        "user_scope": "all", "project": 12,
    }}))[0].text

    assert "Without view_other_timesheet Kimai ignores user=all" in text
    client.get_current_user.assert_not_awaited()  # nothing to compare with for 'all'


@pytest.mark.asyncio
async def test_an_empty_result_for_users_including_the_caller_says_so_too():
    client = _listing_client([])

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {"users": [1, 5]}}))[0].text

    assert "Kimai ignores the user filter, and searches only your own records" in text


@pytest.mark.asyncio
async def test_no_lookups_when_no_row_is_left_to_name():
    """A meta search whose pre-filter returned only near-misses: no project,
    activity or user listing for an empty answer."""
    row = TimesheetEntity(id=1, project=2, activity=1, user=1, begin="2026-09-01T09:00:00+0200",
                          end="2026-09-01T10:00:00+0200", duration=3600,
                          metaFields=[{"name": "ticket", "value": "CA-3760"}])
    client = _listing_client([row])

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {
        "meta": {"name": "ticket", "value": "CA-376"},
    }}))[0].text

    assert text.startswith("Found 0 timesheets")
    client.get_projects.assert_not_awaited()
    client.get_activities.assert_not_awaited()
    client.get_users.assert_not_awaited()


@pytest.mark.asyncio
async def test_own_rows_are_named_without_the_user_listing():
    """user_scope=self prints no user, so GET /users (a 403 for most tokens) is not asked."""
    row = TimesheetEntity(id=1, project=2, activity=1, user=1, begin="2026-09-01T09:00:00+0200",
                          end="2026-09-01T10:00:00+0200", duration=3600,
                          metaFields=[{"name": "ticket", "value": "CA-1"}])
    client = _listing_client([row])
    client.get_projects.return_value = [Project(id=2, name="Relaunch", customer=9, parentTitle="Acme")]

    text = (await dispatch_tool(client, "timesheet", {"action": "list", "filters": {
        "meta": {"name": "ticket", "value": "CA-1"},
    }}))[0].text

    assert "Acme / Relaunch (#2)" in text
    client.get_users.assert_not_awaited()
