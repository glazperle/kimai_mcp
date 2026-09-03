"""``timeBudget`` on the way in vs. on the way out (issue #27).

Kimai is asymmetric here and it is easy to lose an order of magnitude:

* **Reading**, ``timeBudget`` is an integer number of **seconds** -- it is a
  plain ``int`` column on the entity and the serializer sends it as is.
* **Writing**, the API form binds ``timeBudget`` to ``DurationType``
  (``src/Form/EntityFormTrait.php``), which runs
  ``DurationStringToSecondsTransformer`` -> ``Duration::parseDurationString()``
  (``src/Utils/Duration.php``, read at 2.65.0). Any *bare number* -- int or
  string -- takes the ``is_numeric()`` branch into ``parseDecimalFormat()``,
  which multiplies by 3600. A bare number on the write side is therefore
  **decimal hours**, not seconds.

So feeding a value straight back from ``action=get`` into ``action=update``
used to set a budget 3600 times too large: ``timeBudget=7200`` (2 hours read
back) would have been submitted as 7200 *hours*.

The edit forms take an ``int`` as **seconds**, matching the read side, and
convert it to an unambiguous ``H:MM:SS`` colon duration before it goes on the
wire. Strings keep Kimai's documented duration format.
"""

import pytest
from pydantic import ValidationError

from kimai_mcp.models import (
    Activity,
    ActivityEditForm,
    Customer,
    CustomerEditForm,
    Project,
    ProjectEditForm,
    TimesheetEditForm,
)
from kimai_mcp.tools.entity_manager import CustomerEntityHandler, entity_tool
from kimai_mcp.tools.errors import ToolError
from kimai_mcp.tools.registry import validate_arguments
from tests.schema_helpers import entity_data_schema

EDIT_FORMS = [CustomerEditForm, ProjectEditForm, ActivityEditForm]


def _payload(form_cls, **kwargs):
    """What the client would actually POST/PATCH for this form."""
    return form_cls(name="X", **kwargs).model_dump(exclude_none=True, by_alias=True)




# --- the read side is unchanged: seconds, as an int ------------------------

@pytest.mark.parametrize("model", [Customer, Project, Activity])
def test_read_models_still_report_seconds_as_int(model):
    entity = model(id=1, name="X", timeBudget=7200)
    assert entity.time_budget == 7200


# --- the write side accepts what the read side produced --------------------

@pytest.mark.parametrize("form_cls", EDIT_FORMS)
def test_int_is_accepted_and_means_seconds(form_cls):
    """The whole point of #27: an int no longer raises client-side."""
    assert _payload(form_cls, timeBudget=7200)["timeBudget"] == "2:00:00"


@pytest.mark.parametrize("form_cls", EDIT_FORMS)
def test_int_round_trips_a_value_read_from_the_api(form_cls):
    """360000s reads back as '100.00 hours'; it must not become 360000 hours."""
    customer = Customer(id=1, name="Acme", timeBudget=360000)
    assert _payload(form_cls, timeBudget=customer.time_budget)["timeBudget"] == "100:00:00"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00:00"),          # clears the budget
        (59, "0:00:59"),
        (90, "0:01:30"),
        (3600, "1:00:00"),
        (29520, "8:12:00"),      # 8.20h, the case Duration::parseDecimalFormat rounds
        (360000, "100:00:00"),   # more than 24h is fine for a budget
        (-3600, "-1:00:00"),     # Kimai's colon parser accepts a leading sign
    ],
)
def test_seconds_are_formatted_as_a_colon_duration(seconds, expected):
    assert _payload(ActivityEditForm, timeBudget=seconds)["timeBudget"] == expected


@pytest.mark.parametrize("form_cls", EDIT_FORMS)
def test_python_field_name_works_too(form_cls):
    """populate_by_name is on, so time_budget= must behave like timeBudget=."""
    assert _payload(form_cls, time_budget=7200)["timeBudget"] == "2:00:00"


# --- strings keep Kimai's duration format ----------------------------------

@pytest.mark.parametrize("value", ["2h", "2:00", "2:00:00", "1.5", "1,5", "90m", "1h30m"])
def test_duration_strings_are_passed_through_verbatim(value):
    """Kimai owns the duration grammar; we must not reinterpret it."""
    assert _payload(ActivityEditForm, timeBudget=value)["timeBudget"] == value


@pytest.mark.parametrize("value", ["2", "7200", "-90", "007"])
def test_bare_digit_strings_are_rejected_as_ambiguous(value):
    """Kimai would read "7200" as 7200 hours, but it is exactly what a caller
    produces by copying the seconds from a get and sending them as a string."""
    with pytest.raises(ValidationError, match="ambiguous"):
        ActivityEditForm(name="X", timeBudget=value)


@pytest.mark.parametrize("value", ["2 hours", "two", "1:2:3:4", "-2h", "1.5.5"])
def test_malformed_duration_strings_are_rejected_locally(value):
    """Kimai answers 400 for these; failing here says why."""
    with pytest.raises(ValidationError, match="duration"):
        ActivityEditForm(name="X", timeBudget=value)


def test_empty_string_clears_the_budget_like_kimai_does():
    """DurationStringToSecondsTransformer maps '' to 0 before the regex runs."""
    assert _payload(ActivityEditForm, timeBudget="")["timeBudget"] == ""


@pytest.mark.parametrize("value", [" 2h", "2h ", "	2:00 "])
def test_surrounding_whitespace_is_stripped(value):
    """Symfony's TrimListener would strip it anyway; do not reject it locally."""
    assert _payload(ActivityEditForm, timeBudget=value)["timeBudget"] == value.strip()


# --- `break` on timesheets is bound to the same DurationType ----------------

def test_timesheet_break_int_is_seconds_and_goes_out_as_colon_duration():
    """TimesheetEditForm.php binds `break` to DurationType too, so 900 used to
    become 900 hours on the wire."""
    form = TimesheetEditForm(project=1, activity=2, **{"break": 900})
    assert form.model_dump(exclude_none=True, by_alias=True)["break"] == "0:15:00"


def test_timesheet_break_duration_string_passes_through():
    form = TimesheetEditForm(project=1, activity=2, break_duration="15m")
    assert form.model_dump(exclude_none=True, by_alias=True)["break"] == "15m"


def test_timesheet_break_bare_digit_string_is_rejected():
    with pytest.raises(ValidationError, match="break"):
        TimesheetEditForm(project=1, activity=2, break_duration="900")


def test_bool_is_not_silently_treated_as_a_number():
    """bool is an int subclass in Python; True must not mean 1 second."""
    with pytest.raises(ValidationError):
        ActivityEditForm(name="X", timeBudget=True)


def test_omitting_the_budget_sends_nothing():
    assert "timeBudget" not in _payload(ActivityEditForm)


# --- the tool output has to show the value an update takes back ------------

def test_serializer_prints_the_seconds_next_to_the_hours():
    """'2.00 hours' alone invites writing "2" back, which is a duration string
    and would mean two hours only by accident; the seconds are unambiguous."""
    text = CustomerEntityHandler(client=None).serialize_customer(
        Customer(id=1, name="Acme", timeBudget=7200)
    )
    assert "Time Budget: 2.00 hours (7200 seconds)" in text


# --- the tool schema has to let the value through at all -------------------

@pytest.mark.parametrize("entity_type", ["customer", "project", "activity"])
def test_budget_fields_are_reachable_through_the_entity_schema(entity_type):
    """The data schemas are additionalProperties:false, so an omitted field is
    not merely undocumented, it is rejected before the handler ever runs."""
    props = entity_data_schema(entity_type)["properties"]
    assert {"budget", "timeBudget", "budgetType"} <= set(props)
    assert set(props["timeBudget"]["type"]) == {"integer", "string"}
    assert props["budgetType"]["enum"] == ["month"]


@pytest.mark.parametrize("entity_type", ["customer", "project", "activity"])
def test_validate_arguments_accepts_a_budget(entity_type):
    validate_arguments(entity_tool(), {
        "type": entity_type,
        "action": "update",
        "id": 1,
        "data": {"budget": 500.0, "timeBudget": 7200, "budgetType": "month"},
    })


@pytest.mark.parametrize("entity_type", ["customer", "project", "activity"])
def test_the_schema_still_rejects_an_unknown_field(entity_type):
    """Guard against 'fixing' this by loosening additionalProperties."""
    with pytest.raises(ToolError):
        validate_arguments(entity_tool(), {
            "type": entity_type,
            "action": "update",
            "id": 1,
            "data": {"timeBudgett": 7200},
        })


@pytest.mark.parametrize("entity_type", ["customer", "project", "activity"])
def test_the_schema_documents_the_seconds_vs_hours_split(entity_type):
    """The description is the only place an LLM learns that '2' is 2 hours."""
    description = entity_data_schema(entity_type)["properties"]["timeBudget"]["description"].lower()
    assert "seconds" in description
    assert "hours" in description


def test_activity_schema_is_closed_and_typed():
    """A typo in an activity field used to become an empty PATCH reported as
    'Updated'; the activity branch is additionalProperties:false now."""
    schema = entity_data_schema("activity")
    assert schema["additionalProperties"] is False
    assert {"name", "project", "teams", "color", "visible", "billable", "metaFields"} <= set(schema["properties"])
    assert schema["properties"]["teams"]["type"] == "array"


@pytest.mark.parametrize("form_cls", EDIT_FORMS)
def test_teams_is_a_list_of_ids_on_the_create_forms(form_cls):
    """Kimai's TeamType is `multiple => true`: an array of team ids."""
    assert form_cls(name="X", teams=[1, 2]).model_dump(exclude_none=True)["teams"] == [1, 2]


@pytest.mark.parametrize("entity_type", ["customer", "project", "activity"])
def test_teams_is_reachable_on_create_for_all_three_types(entity_type):
    """Kimai binds `teams` (an array of ids) on create for all three entities."""
    props = entity_data_schema(entity_type)["properties"]
    assert props["teams"]["type"] == "array"
    validate_arguments(entity_tool(), {
        "type": entity_type, "action": "create",
        "data": {"name": "Acme", "teams": [1, 2], **({"customer": 1} if entity_type == "project" else {}),
                 **({"country": "DE", "currency": "EUR", "timezone": "Europe/Berlin"} if entity_type == "customer" else {})},
    })


def test_activity_update_does_not_require_a_name():
    """The schema promises `name` is required for create only; the form must
    agree, or `action=update data={"timeBudget": 7200}` dies in Pydantic."""
    assert ActivityEditForm(timeBudget=7200).model_dump(exclude_none=True, by_alias=True) == {"timeBudget": "2:00:00"}
