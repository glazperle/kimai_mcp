"""Customer fields and list options from Kimai 2.62 / 2.63.

``language`` and ``invoiceEmail`` are new Customer fields (kimai/kimai#5857,
#5855). They have to survive parsing, serialization and the create/update form,
and the ``entity`` schema is ``additionalProperties: false`` for customer data,
so a missing schema entry would silently block writing them.

Which fields a response actually contains follows the serializer groups in
``src/Entity/Customer.php`` (read at 2.65.0), and they are easy to get wrong:

* ``Default`` covers ``language`` and ``metaFields``, so a **plain** listing
  already carries them - ``full=1`` is not needed for those.
* ``Customer_Details`` is what ``full=1`` (Kimai 2.62+) adds: ``vatId`` plus
  the structured address (``addressLine1``-``3``, ``postCode``, ``city``).
* ``Customer_Entity`` is get/create/update only: ``email``, ``contact``,
  ``address``, ``invoiceEmail``, ``buyerReference`` and the budget fields never
  appear in a listing at all, no matter what ``full`` says.
"""

from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import KimaiClient
from kimai_mcp.models import Activity as ActivityModel
from kimai_mcp.models import Customer, CustomerEditForm, CustomerExtended, User
from kimai_mcp.models import Project as ProjectModel
from kimai_mcp.tools.entity_manager import (
    CustomerEntityHandler,
    ProjectEntityHandler,
    entity_tool,
)

CUSTOMER_SCHEMA_TITLE = "Schema for creating/editing customer entities."


def _customer_data_schema() -> dict:
    """The create/update data schema for type=customer out of the tool schema."""
    for branch in entity_tool().input_schema["allOf"]:
        data = branch.get("then", {}).get("properties", {}).get("data", {})
        if data.get("description") == CUSTOMER_SCHEMA_TITLE:
            return data
    raise AssertionError("customer create/update schema not found")


def test_customer_model_parses_new_fields():
    customer = Customer(
        id=7, name="Acme", language="de", invoiceEmail="billing@acme.example"
    )
    assert customer.language == "de"
    assert customer.invoice_email == "billing@acme.example"


def test_customer_model_defaults_new_fields_to_none():
    """Kimai < 2.63 does not send the fields at all."""
    customer = Customer(id=7, name="Acme")
    assert customer.language is None
    assert customer.invoice_email is None


def test_edit_form_sends_new_fields_under_api_names():
    form = CustomerEditForm(language="de", invoiceEmail="billing@acme.example")
    payload = form.model_dump(exclude_none=True, by_alias=True)
    assert payload == {"language": "de", "invoiceEmail": "billing@acme.example"}


def test_serialize_customer_renders_new_fields():
    customer = CustomerExtended(
        id=7, name="Acme", language="de", invoiceEmail="billing@acme.example"
    )
    text = CustomerEntityHandler(client=None).serialize_customer(customer)
    assert "Language: de" in text
    assert "Invoice Email: billing@acme.example" in text


def test_customer_model_parses_the_whole_detail_set():
    """Every serializer group has to land in the model, not just the new fields.

    The model used to stop at the Default group, so a full=1 listing and even
    action=get silently discarded vatId, the address, the budget and the meta
    fields, and the tool output looked identical to the short form.
    """
    customer = Customer(
        id=7, name="Acme", vatId="DE123456789", addressLine1="Hauptstrasse 1",
        addressLine2="Hinterhaus", addressLine3="c/o Meier", postCode="10115",
        city="Berlin", contact="Erika Musterfrau", address="legacy address",
        email="info@acme.example", buyerReference="LC-4711", budget=5000.0,
        timeBudget=360000, budgetType="month",
        metaFields=[{"name": "Kostenstelle", "value": "K-42"}],
    )
    assert customer.vat_id == "DE123456789"
    assert customer.address_line1 == "Hauptstrasse 1"
    assert customer.address_line3 == "c/o Meier"
    assert customer.post_code == "10115"
    assert customer.buyer_reference == "LC-4711"
    assert customer.time_budget == 360000
    assert customer.budget_type == "month"
    assert customer.meta_fields[0].name == "Kostenstelle"


def test_serialize_customer_renders_the_detail_set():
    customer = Customer(
        id=7, name="Acme", currency="EUR", vatId="DE123456789",
        addressLine1="Hauptstrasse 1", postCode="10115", city="Berlin",
        email="info@acme.example", contact="Erika Musterfrau",
        buyerReference="LC-4711", budget=5000.0, budgetType="month",
        timeBudget=360000,
    )
    text = CustomerEntityHandler(client=None).serialize_customer(customer)
    assert "VAT ID: DE123456789" in text
    assert "Address: Hauptstrasse 1, 10115 Berlin" in text
    assert "Email: info@acme.example" in text
    assert "Contact: Erika Musterfrau" in text
    assert "Buyer Reference: LC-4711" in text
    assert "Budget: 5000.0 EUR per month" in text
    assert "Time Budget: 100.00 hours" in text


def test_serialize_customer_falls_back_to_the_legacy_address():
    """Older instances only send the unstructured 'address' field."""
    customer = Customer(id=7, name="Acme", address="Hauptstrasse 1, 10115 Berlin")
    text = CustomerEntityHandler(client=None).serialize_customer(customer)
    assert "Address: Hauptstrasse 1, 10115 Berlin" in text


def test_short_form_customer_stays_terse():
    """A plain listing must not grow empty labels for the absent detail fields."""
    text = CustomerEntityHandler(client=None).serialize_customer(
        Customer(id=8, name="Short Form")
    )
    for label in ("VAT ID", "Address", "Budget", "Buyer Reference", "Contact"):
        assert label not in text


@pytest.mark.parametrize(
    "model_cls", [Customer, ProjectModel, ActivityModel],
    ids=["customer", "project", "activity"],
)
def test_meta_fields_parse_on_the_base_models(model_cls):
    """metaFields is in the Default group, so listings carry them too.

    Only the *Extended models used to declare the field, so every list result
    dropped the custom fields Kimai had already sent.
    """
    entity = model_cls(id=1, name="X", metaFields=[{"name": "Festival", "value": "Nectar"}])
    assert entity.meta_fields[0].value == "Nectar"


def test_customer_schema_accepts_new_fields():
    """additionalProperties is false, so the fields need explicit entries."""
    schema = _customer_data_schema()
    assert schema["additionalProperties"] is False
    assert "language" in schema["properties"]
    assert "invoiceEmail" in schema["properties"]


def test_list_filter_schema_offers_full():
    schema = entity_tool().input_schema["properties"]["filters"]["properties"]
    assert schema["full"]["type"] == "boolean"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filters", "expected"),
    [({"full": True}, 1), ({"full": False}, None), ({}, None)],
    ids=["full_true", "full_false", "absent"],
)
async def test_list_passes_full_to_the_api(filters, expected):
    client = AsyncMock(spec=KimaiClient)
    client.get_customers.return_value = []

    await CustomerEntityHandler(client=client).list(filters)

    sent = client.get_customers.call_args.args[0]
    assert sent.full == expected
    params = sent.model_dump(exclude_none=True, by_alias=True)
    assert params.get("full") == expected


# ---------------------------------------------------------------------------
# The rest of the model surface, verified against Kimai's schema definitions
# (scripts/audit_api_models.py) and a live 2.65 instance.
# ---------------------------------------------------------------------------


def test_embedded_teams_parse_as_stubs():
    """Kimai embeds teams as {id, name, color}, not as full Team objects.

    Modelling them as `Team` would recurse (team -> customers -> teams), so the
    stub type exists; before it, every customer/project/activity dropped the
    team assignment entirely.
    """
    project = ProjectModel(
        id=1, name="P",
        teams=[{"id": 3, "name": "Verwaltung", "color": None},
               {"id": 4, "name": "Administration", "color": "#fff"}],
    )
    assert [t.name for t in project.teams] == ["Verwaltung", "Administration"]


def test_project_carries_timeframe_order_and_budget():
    """A listing sends start/end/order*, the entity adds the budget."""
    project = ProjectModel(
        id=1, name="P", customer=2, parentTitle="Acme",
        start="2026-01-01T00:00:00+0100", end="2026-12-31T00:00:00+0100",
        orderNumber="PO-42", orderDate="2025-12-01T00:00:00+0100",
        budget=1000.0, budgetType="month", timeBudget=7200,
    )
    assert project.order_number == "PO-42"
    assert project.parent_title == "Acme"
    assert project.start.year == 2026
    assert project.time_budget == 7200


def test_serialize_project_renders_the_new_fields():
    text = ProjectEntityHandler(client=None).serialize_project(ProjectModel(
        id=1, name="P", customer=2, parentTitle="Acme",
        start="2026-01-01T00:00:00+0100", orderNumber="PO-42",
        budget=1000.0, budgetType="month",
        teams=[{"id": 3, "name": "Verwaltung"}],
    ))
    assert "Customer: Acme (ID: 2)" in text
    assert "Order Number: PO-42" in text
    assert "Timeframe: 2026-01-01 - open" in text
    assert "Budget: 1000.0 per month" in text
    assert "Teams: Verwaltung" in text


def test_user_model_covers_the_default_group():
    user = User(id=1, username="a", email="a@b.de", accountNumber="P-1",
                systemAccount=False, avatar="https://x/y.png", initials="AB",
                language="de", locale="de", timezone="Europe/Berlin")
    assert user.email == "a@b.de"
    assert user.account_number == "P-1"
    assert user.system_account is False
