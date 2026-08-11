"""Customer fields and list options added by Kimai 2.62 / 2.63.

- ``language`` and ``invoiceEmail`` are new Customer fields (kimai/kimai#5857,
  #5855). They have to survive parsing, serialization and the create/update
  form, and the ``entity`` schema has ``additionalProperties: false`` for
  customer data, so a missing schema entry would silently block them.
- ``GET /api/customers`` gained ``full=0|1`` (Kimai 2.62), which is what returns
  the detail fields in a listing.
"""

from unittest.mock import AsyncMock

import pytest

from kimai_mcp.client import KimaiClient
from kimai_mcp.models import Customer, CustomerEditForm, CustomerExtended
from kimai_mcp.tools.entity_manager import CustomerEntityHandler, entity_tool

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
    "filters, expected",
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
