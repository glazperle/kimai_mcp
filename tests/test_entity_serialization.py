"""Regression tests for entity meta-field serialization.

create/update responses parse `metaFields` into `MetaField` objects (the
`*Extended` models), unlike list/get which use the base models. Serializing a
`MetaField` object previously raised `'MetaField' object has no attribute 'get'`
because the dict/object branch was inverted.
"""
import pytest

from kimai_mcp.models import ProjectExtended, CustomerExtended, ActivityExtended
from kimai_mcp.tools.entity_manager import (
    ProjectEntityHandler,
    CustomerEntityHandler,
    ActivityEntityHandler,
)


@pytest.mark.parametrize("handler_cls, model_cls, method", [
    (ProjectEntityHandler, ProjectExtended, "serialize_project"),
    (CustomerEntityHandler, CustomerExtended, "serialize_customer"),
    (ActivityEntityHandler, ActivityExtended, "serialize_activity"),
])
def test_serialize_renders_metafield_objects(handler_cls, model_cls, method):
    entity = model_cls(id=1, name="Test", metaFields=[{"name": "Festival", "value": "Nectar"}])
    text = getattr(handler_cls(client=None), method)(entity)
    assert "Festival: Nectar" in text
