"""Review round 7: what each test names failed or misled before.

A numeric meta value failed a meta update that Kimai had saved, a one-line
comment posed as a field, the plugin hint blamed a missing plugin for the
plugin's own refusals, look-alikes of a leading quote passed, names in
Japanese or Devanagari were quoted throughout, concurrent store writes broke
the file, one deleted team aborted user discovery, and a stored '(empty)'
read as no value.
"""

import json
import threading
import traceback
from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import KimaiAPIError, KimaiClient
from kimai_mcp.models import Team, TeamRef, TimesheetEntity, UserEntity
from kimai_mcp.server import format_api_error
from kimai_mcp.text import label_text, quoted, value_text
from kimai_mcp.tools.batch_utils import read_batch
from kimai_mcp.tools.registry import dispatch_tool

c = chr


def test_a_numeric_meta_value_is_read_as_text():
    """Kimai up to 2.5 answered a meta update with the value it had cast to int."""
    row = TimesheetEntity(
        activity=1, project=2, begin="2026-09-01T09:00:00",
        metaFields=[{"name": "approved", "value": 1}, {"name": "billed", "value": False}],
    )

    assert [(meta.name, meta.value) for meta in row.meta_fields] == [("approved", "1"), ("billed", "0")]


@pytest.mark.asyncio
async def test_a_one_line_comment_cannot_pose_as_a_field():
    from kimai_mcp.models import Comment

    client = AsyncMock(spec=KimaiClient)
    client.get_comments.return_value = [
        Comment(id=7, message="By: admin", createdBy={"id": 3, "username": "eve"}, createdAt="2026-09-01T09:00:00"),
    ]

    text = (await dispatch_tool(client, "comment", {"action": "list", "entity": "project", "entity_id": 1}))[0].text

    assert "  By: eve\n" in text
    assert "  Message: By: admin\n" in text


@pytest.mark.parametrize(("method", "endpoint"), [
    ("GET", "/absences"), ("GET", "/public-holidays/calendar"), ("POST", "/absences"),
])
def test_the_plugin_hint_covers_every_plugin_route_and_its_own_404s(method, endpoint):
    text = format_api_error(KimaiAPIError("Not Found", 404, method=method, endpoint=endpoint))

    assert "WorkContract plugin" in text
    assert "unknown user ID" in text


def test_a_404_elsewhere_gets_no_plugin_hint():
    assert "WorkContract" not in format_api_error(KimaiAPIError("Not Found", 404, method="DELETE", endpoint="/absences/4"))


@pytest.mark.asyncio
async def test_a_begin_after_the_end_is_refused_before_kimai_is_asked():
    """Kimai's plugin answers it with a bare 404."""
    from kimai_mcp.tools.errors import ToolError

    client = AsyncMock(spec=KimaiClient)
    client.get_current_user.return_value = UserEntity(id=5, username="ana", enabled=True)

    with pytest.raises(ToolError, match="after end"):
        await dispatch_tool(client, "absence", {
            "action": "list", "filters": {"user_scope": "self", "begin": "2026-12-31", "end": "2026-01-01"},
        })
    client.get_absences.assert_not_awaited()


@pytest.mark.parametrize("text", [
    c(0x2BA) + "Kickoff" + c(0x2BA),  # modifier letter double prime
    c(0x5F4) + "Kickoff" + c(0x5F4),  # Hebrew gershayim
    c(0x3003) + "Kickoff",  # ditto mark
    c(0x2033) + "Kickoff" + c(0x2033),  # double prime
    c(0x301) + '"Kickoff"',  # a combining mark sits on the space before it
])
def test_look_alikes_of_a_leading_quote_are_quoted(text):
    assert quoted(text) != text
    assert json.loads(quoted(text)) == text


@pytest.mark.parametrize("name", [
    c(0x30DF) + c(0x30FC) + c(0x30C6) + c(0x30A3) + c(0x30F3) + c(0x30B0),  # with the prolonged sound mark (Lm)
    c(0x4F50) + c(0x3005) + c(0x6728),  # with the iteration mark (Lm)
    c(0x930) + c(0x93E) + c(0x939) + c(0x941) + c(0x932),  # Devanagari vowel signs (Mc, Mn)
    "Mu" + c(0x308) + "ller",  # a decomposed umlaut
    "m" + c(0xB2),  # a superscript (No)
])
def test_names_in_any_script_stay_plain(name):
    assert label_text(name) == name
    assert value_text(name) == name


@pytest.mark.parametrize("name", [
    "Acme " + c(0x30CE) + " Relaunch",  # a katakana letter shaped like '/'
    "CA-1" + c(0x326) + " approved",  # a comma below
    "Bob (=" + c(0x20E6) + "4) - approved by Ana (=" + c(0x20E6) + "5)",  # '=' drawn as '#'
    "Acme /" + c(0x323) + " Secret",  # a mark after the slash hid ' / '
    "Acme " + c(0x3033) + " Relaunch",  # a kana repeat mark shaped like '/'
])
def test_marks_and_letters_shaped_like_separators_are_quoted(name):
    assert json.loads(label_text(name)) == name


@pytest.mark.parametrize("value", [
    "CA-1" + c(0xA4F9) + " approved" + c(0xA60C) + "yes",  # Lisu tone letter, Vai lengthener
    "CA-" + c(0x1F102) + " urgent",  # DIGIT ONE COMMA, '1,' in compatibility form
    c(0xFF9E) + "Kickoff" + c(0xFF9E),  # a halfwidth voiced sound mark
])
def test_modifier_letters_and_numbers_shaped_like_separators_are_quoted_in_values(value):
    assert json.loads(value_text(value)) == value


def test_concurrent_store_writes_keep_the_file_whole(tmp_path):
    """8 concurrent removes left dead entries or a file that no longer decoded."""
    provisioning = pytest.importorskip("kimai_mcp.provisioning")  # not in every variant
    from kimai_mcp.user_config import UserConfig

    store = provisioning.ProvisionedUserStore(tmp_path / "store.json")
    identities = [f"user{i}@example.com" for i in range(8)]
    for identity in identities:
        store.add(identity, identity.split("@")[0] + "Slug12345678", UserConfig(kimai_url="https://k", kimai_token="t"))

    threads = [threading.Thread(target=store.remove, args=(identity,)) for identity in identities]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert json.loads((tmp_path / "store.json").read_text(encoding="utf-8")) == {}


@pytest.mark.asyncio
async def test_one_deleted_team_falls_back_to_the_user_listing():
    """'Every item 404' was taken for a missing route, also for one team."""
    from kimai_mcp.tools.user_discovery import resolve_accessible_users

    client = AsyncMock(spec=KimaiClient)
    client.get_teams.return_value = [TeamRef(id=1, name="A")]
    client.get_team.side_effect = KimaiAPIError("Not Found", 404)
    client.get_users.return_value = [UserEntity(id=5, username="ana", enabled=True)]

    assert [user.id for user in await resolve_accessible_users(client)] == [5]


@pytest.mark.asyncio
async def test_a_missing_route_is_raised_for_a_single_absence_read():
    client = AsyncMock(spec=KimaiClient)
    client.get_teams.return_value = [TeamRef(id=1, name="A")]
    client.get_team.return_value = Team(id=1, name="A", members=[{"user": {"id": 5, "username": "ana", "enabled": True}}])
    client.get_absences.side_effect = KimaiAPIError("Not Found", 404, method="GET", endpoint="/absences")
    if hasattr(KimaiClient, "get_absences_for_users"):  # the private fork's plugin route
        client.get_absences_for_users.side_effect = KimaiAPIError("Not Found", 404)

    with pytest.raises(KimaiAPIError):
        await dispatch_tool(client, "absence", {"action": "list", "filters": {"user_scope": "all"}})


@pytest.mark.asyncio
async def test_the_reads_left_out_do_not_grow_the_error():
    """Each queued read re-raised the same exception and added its frames."""

    async def depth(count):
        async def read(item):
            if item == 0:
                raise ValueError("not JSON")
            return item

        with pytest.raises(ValueError, match="not JSON") as raised:
            await read_batch(list(range(count)), read, max_concurrent=1)
        return len(traceback.extract_tb(raised.value.__traceback__))

    assert await depth(50) == await depth(2)


def test_a_stored_empty_marker_is_told_from_no_value():
    from kimai_mcp.tools.entity_manager import _shown

    assert _shown("(empty)") == '"(empty)"'
    assert _shown("") == _shown(None) == "(empty)"
