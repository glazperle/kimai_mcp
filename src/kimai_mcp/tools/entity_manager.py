"""Consolidated Entity Manager tool for all CRUD operations."""
import builtins
import logging
from types import UnionType
from typing import Annotated, Literal, Union, get_args, get_origin

from mcp.types import TextContent, Tool

from ..client import KimaiAPIError, KimaiClient
from ..models import (
    ActivityEditForm,
    ActivityFilter,
    ActivityOrderBy,
    Customer,
    CustomerEditForm,
    CustomerFilter,
    CustomerOrderBy,
    InvoiceEditForm,
    InvoiceFilter,
    InvoiceStatus,
    ProjectEditForm,
    ProjectFilter,
    ProjectOrderBy,
    PublicHolidayFilter,
    SortOrder,
    TagEditForm,
    TagFilter,
    TeamEditForm,
    UserCreateForm,
    UserEditForm,
    UserFilter,
    UserOrderBy,
)
from .batch_utils import execute_batch, format_batch_result
from .errors import ToolError
from .user_discovery import resolve_accessible_users

logger = logging.getLogger(__name__)

# Budget block shared by the customer, project and activity data schemas. Those
# schemas are additionalProperties:false, so a field that is missing here cannot
# be written at all - it is rejected by validate_arguments before the handler
# runs, not merely left undocumented.
#
# `timeBudget` is one field with two meanings (see models._normalize_duration):
# Kimai serializes it as seconds but parses a bare number on write as hours.
#
def _budget_schema() -> dict:
    return {
        "budget": {
            "type": "number",
            "description": "Money budget, in the customer's currency. 0 removes it.",
        },
        "timeBudget": {
            "type": ["integer", "string"],
            "description": (
                "Time budget. An integer is SECONDS, the same unit action=get "
                "returns, so a value read from Kimai can be written straight back "
                "(7200 = 2 hours). A string is a Kimai duration string, where a "
                'bare number is HOURS: "2.0", "2h" and "2:00" all mean two hours, '
                'while "90m" and "1:30" mean 90 minutes. A bare-digit string such '
                'as "7200" is rejected as ambiguous. 0 removes the budget. Kimai '
                "only accepts these fields when the token holds the 'budget' resp. "
                "'time' permission for the entity. "
                "https://www.kimai.org/documentation/duration-format.html"
            ),
        },
        "budgetType": {
            "type": "string",
            "enum": ["month"],
            "description": (
                "Set to 'month' to make 'budget' and 'timeBudget' a recurring "
                "monthly allowance. Omit to leave the stored type unchanged (a new "
                "entity then gets one total budget over its whole lifetime). "
                "Reverting 'month' to a lifetime budget is not possible through "
                "this tool; use the Kimai UI for that."
            ),
        },
    }


def _order_by_description() -> str:
    """The sort fields Kimai's API takes, per type, from the filter models.

    The API's ``orderBy`` is a strict alternation (``Rest\\QueryParam``); the
    UI-only sort keys of the *Query classes answer 400. Built from the same
    Literals the audit script checks against Kimai, so the text cannot drift.
    """
    per_type = {
        "project": ProjectOrderBy,
        "activity": ActivityOrderBy,
        "customer": CustomerOrderBy,
        "user": UserOrderBy,
    }
    values = "; ".join(f"{t}: {', '.join(get_args(v))}" for t, v in per_type.items())
    return f"Sort field. Allowed per type - {values}."


def _json_type(annotation) -> dict:
    """JSON schema for a form field annotation (Optional and Annotated unwrapped)."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _json_type(get_args(annotation)[0])
    if origin in (Union, UnionType):
        return _json_type(next(a for a in get_args(annotation) if a is not type(None)))
    if origin is Literal:
        return {"type": "string", "enum": list(get_args(annotation))}
    if origin is list:
        return {"type": "array", "items": _json_type(get_args(annotation)[0])}
    simple = {bool: "boolean", int: "integer", float: "number", str: "string"}
    return {"type": simple[annotation]} if annotation in simple else {"type": "object"}


def _form_data_schema(form, description: str, notes: dict | None = None, override: dict | None = None,
                      required: bool = False) -> dict:
    """The closed ``data`` object of a create/update branch, derived from its form model.

    Derived rather than written by hand, so the schema cannot lack a field the
    request model sends, or offer one it drops. ``notes`` adds descriptions,
    ``override`` replaces a field's schema; ``required`` takes the model's
    required fields over.
    """
    properties = {}
    for name, info in form.model_fields.items():
        alias = info.alias or name
        prop = dict((override or {}).get(alias) or _json_type(info.annotation))
        if notes and alias in notes:
            prop["description"] = notes[alias]
        properties[alias] = prop
    schema = {"type": "object", "description": description, "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = [info.alias or name for name, info in form.model_fields.items() if info.is_required()]
    return schema


def _data_branch(entity: str, actions: list[str], data: dict) -> dict:
    return {
        "if": {"properties": {"type": {"const": entity}, "action": {"enum": actions}}},
        "then": {"properties": {"data": data}, "required": ["data"]},
    }


def _user_branches() -> list[dict]:
    # One line instead of a note per field: every word here is sent with each request.
    gated = (
        "Fields to change; Kimai keeps the rest. Permission-gated: language, locale, timezone "
        "(preferences); supervisor; roles, systemAccount, requiresPasswordReset (roles; 2.68+); "
        "enabled (not on yourself); avatar (only if the instance enables avatars)."
    )
    return [
        _data_branch("user", ["create"], _form_data_schema(UserCreateForm, "Fields of a new user.", required=True)),
        _data_branch("user", ["update"], _form_data_schema(UserEditForm, gated)),
    ]


def _team_tag_invoice_branches() -> list[dict]:
    members = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"user": {"type": "integer"}, "teamlead": {"type": "boolean"}},
            "required": ["user"],
        },
        "description": "Replaces the member list; to change one member use team_access.",
    }
    return [
        _data_branch("team", ["create", "update"], _form_data_schema(
            TeamEditForm, "Create needs name and members.", override={"members": members})),
        _data_branch("tag", ["create"], _form_data_schema(TagEditForm, "Tag fields.")),
        _data_branch("invoice", ["update"], _form_data_schema(
            InvoiceEditForm, "Kimai 2.68+, permission edit_invoice. Meta fields: meta tool.",
            {"paymentDate": "YYYY-MM-DD"})),
    ]


def _meta_fields_schema(entity: str) -> dict:
    return {
        "type": "array",
        "description": f"Custom meta fields for this {entity}",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "string"}
            },
            "required": ["name", "value"]
        }
    }


# Preference aliases for more intuitive names
PREFERENCE_ALIASES = {
    # Vacation
    "vacation_days": "holidays",
    "annual_leave": "holidays",
    "vacation": "holidays",
    # Work time
    "weekly_hours": "hours_per_week",
    # Contract type
    "contract_type": "work_contract_type",
}


def normalize_preference_name(name: str) -> str:
    """Convert intuitive preference names to Kimai API names."""
    return PREFERENCE_ALIASES.get(name.lower(), name)


def entity_tool() -> Tool:
    """Define the consolidated entity management tool."""
    return Tool(
        name="entity",
        description="""Universal entity management for Kimai (projects, activities, customers, users, teams, tags, invoices, holidays).

COMMON TASKS:
- Change vacation days: action=set_preferences, type=user, id=USER_ID, preferences=[{name:"holidays", value:"25"}]
- Lock timesheet month: action=lock_month, type=user, id=USER_ID, month="2024-12-01"
- Create project: action=create, type=project, data={name:"...", customer:ID}
- Lock a project's past: action=update, type=project, id=ID, data={lockedUntil:"2026-08-31T00:00:00"} (Kimai 2.66+)
- Invoices: list/get; update status, payment date, comment (Kimai 2.68+, edit_invoice); delete (2.66+, delete_invoice). Invoices are created in Kimai's UI

USER PREFERENCES (action=set_preferences, type=user only):
  holidays (vacation days), hours_per_week, work_contract_type, work_monday..work_sunday""",
        input_schema={
            "type": "object",
            "required": ["type", "action"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["project", "activity", "customer", "user", "team", "tag", "invoice", "holiday"],
                    "description": "The entity type to operate on"
                },
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete", "lock_month", "unlock_month", "batch_delete", "set_preferences"],
                    "description": """The action to perform:
                    - list: List entities matching the given filters
                    - create: Create a new entity
                    - get: Get a single entity by ID
                    - update: Update an existing entity by ID
                    - delete: Delete an existing entity by ID
                    - lock_month: Lock working time months for a user (type=user only)
                    - unlock_month: Unlock working time months for a user (type=user only)
                    - batch_delete: Delete multiple entities by IDs (requires 'ids' parameter)
                    - set_preferences: Set user preferences for work contracts (type=user only)
                    """
                },
                "id": {
                    "type": "integer",
                    "description": "Entity ID (required for get, update, delete actions)"
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for list action (e.g., visible, term, customer, project). A filter that does not apply to the type is ignored, and the result says so.",
                    "properties": {
                        "visible": {"type": "integer", "enum": [1, 2, 3], "description": "1=visible, 2=hidden, 3=both"},
                        "term": {"type": "string",
                                 "description": "Search exact term. For entity types other then invoice and holiday you can just list all if you don't find it on first try."},
                        "customer": {"type": "integer", "description": "Customer ID filter (for projects)"},
                        "project": {"type": "integer", "description": "Project ID filter (for activities)"},
                        "projects": {"type": "array", "items": {"type": "integer"},
                                     "description": "Several project IDs (for activities)"},
                        "globals": {"type": "string", "enum": ["0", "1"], "description": "Global activities filter"},
                        "global_activities": {"type": "string", "enum": ["0", "1"],
                                              "description": "type=project: only projects that do (1) or do not (0) allow global activities"},
                        "ignore_dates": {
                            "type": "boolean",
                            "description": "type=project: include finished and future projects (Kimai's default: running today only)."
                        },
                        "name": {"type": "string", "description": "type=tag: tag name filter (term works too)"},
                        "group": {"type": "integer", "description": "type=holiday: public holiday group ID"},
                        "page": {"type": "integer", "description": "Page number"},
                        "size": {"type": "integer", "description": "Page size"},
                        "order_by": {"type": "string", "description": _order_by_description()},
                        "order": {"type": "string", "enum": list(get_args(SortOrder)), "description": "Sort order"},
                        "begin": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Start date and time filter (format: YYYY-MM-DDThh:mm:ss, e.g., 2023-10-27T09:30:00) Only records after this date will be included. type=project: only projects running on that day."
                        },
                        "end": {
                            "type": "string",
                            "format": "date-time",
                            "description": "End date and time filter (format: YYYY-MM-DDThh:mm:ss, e.g., 2023-10-27T17:00:00). Only records before this date will be included. type=project: only projects running on that day."
                        },
                        "customers": {"type": "array", "items": {"type": "integer"},
                                      "description": "Customer IDs (for projects and invoices)"},
                        "status": {"type": "array", "items": {"type": "string", "enum": list(get_args(InvoiceStatus))},
                                   "description": "Status filter (for invoices)"},
                        "full": {
                            "type": "boolean",
                            "description": "For type=customer: return the detailed customer records, which adds vatId and the structured address (addressLine1-3, postCode, city). Requires Kimai 2.62+ and the 'details_customer' permission; without the permission Kimai silently returns the short form instead of failing. Fields like email, contact, invoiceEmail and buyerReference are never part of a listing, use action=get for those. Since Kimai 2.66 budget/timeBudget/budgetType ARE part of listings, but only for records the token holds the 'budget' resp. 'time' permission for; before 2.66 they were get-only."
                        }
                    }
                },
                "data": {
                    "type": "object",
                    "description": "Data for create/update actions (entity-specific fields)",
                    "additionalProperties": True
                },
                "month": {
                    "type": "string",
                    "description": "Month for lock_month/unlock_month actions (YYYY-MM-DD format). For lock: all months before and including this one will be locked. For unlock: all months from this one to end of year will be unlocked.",
                    "pattern": "[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1])"
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of entity IDs for batch operations (batch_delete, bulk lock_month/unlock_month)."
                },
                "user_scope": {
                    "type": "string",
                    "enum": ["all"],
                    "description": "Set to 'all' to apply lock_month/unlock_month to all active users. Use instead of 'id' or 'ids'."
                },
                "preferences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Preference name"},
                            "value": {"type": "string", "description": "Preference value"}
                        },
                        "required": ["name"]
                    },
                    "description": """List of preferences for set_preferences action (type=user only).

VACATION:
- holidays: Vacation days per year (e.g., "25", "30"). Aliases: vacation_days, annual_leave

WORK CONTRACT:
- work_contract_type: "week" (weekly hours) or "day" (daily hours)
- hours_per_week: Weekly hours in seconds (144000 = 40h, 126000 = 35h). Alias: weekly_hours
- work_monday..work_sunday: Daily hours in seconds (28800 = 8h, 0 = no work)
- work_days_week: Work days as "1,2,3,4,5" (1=Monday)

CONTRACT PERIOD:
- work_start_day: Contract start date (YYYY-MM-DD)
- work_last_day: Contract end date (YYYY-MM-DD)

OTHER:
- public_holiday_group: Holiday region ID (e.g., "1")
- hourly_rate/internal_rate: User rates"""
                }
            },
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "type": {"const": "customer"},
                            "action": {"enum": ["create", "update"]}
                        }
                    },
                    "then": {
                        "properties": {
                            "data": {
                                "type": "object",
                                "description": "Schema for creating/editing customer entities.",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "minLength": 2,
                                        "maxLength": 150,
                                        "description": "Customer name, required for create action."
                                    },
                                    "number": {
                                        "type": "string",
                                        "maxLength": 50,
                                        "description": "Customer number (internal identifier)"
                                    },
                                    "comment": {
                                        "type": "string",
                                        "description": "Any additional comments for the customer"
                                    },
                                    "visible": {
                                        "type": "boolean",
                                        "default": True,
                                        "description": "Whether the customer is visible"
                                    },
                                    "billable": {
                                        "type": "boolean",
                                        "default": True,
                                        "description": "Whether the customer is billable"
                                    },
                                    "company": {
                                        "type": "string",
                                        "maxLength": 100,
                                        "description": "Customer's company name"
                                    },
                                    "vatId": {
                                        "type": "string",
                                        "maxLength": 50,
                                        "description": "VAT ID of the customer"
                                    },
                                    "contact": {
                                        "type": "string",
                                        "maxLength": 100,
                                        "description": "Contact person's name"
                                    },
                                    "address": {
                                        "type": "string",
                                        "description": (
                                            "Deprecated single-line address. Kimai only puts this field on "
                                            "the form when the customer ALREADY has a non-empty legacy "
                                            "address, which is never the case on create, so sending it "
                                            "usually fails the whole request with 'This form should not "
                                            "contain extra fields.' Use addressLine1-3 / postCode / city."
                                        )
                                    },
                                    "addressLine1": {
                                        "type": "string",
                                        "description": "Street and number"
                                    },
                                    "addressLine2": {
                                        "type": "string",
                                        "description": "Additional address line"
                                    },
                                    "addressLine3": {
                                        "type": "string",
                                        "description": "Additional address line"
                                    },
                                    "postCode": {
                                        "type": "string",
                                        "description": "Postal code"
                                    },
                                    "city": {
                                        "type": "string",
                                        "description": "City"
                                    },
                                    "buyerReference": {
                                        "type": "string",
                                        "description": "Buyer reference (Leitweg-ID), used on e-invoices"
                                    },
                                    "country": {
                                        "type": "string",
                                        "maxLength": 2,
                                        "description": "Two-letter ISO country code (e.g., 'US', 'DE'), required for create action.",
                                        "pattern": "^[A-Z]{2}$"
                                    },
                                    "currency": {
                                        "type": "string",
                                        "maxLength": 3,
                                        "default": "EUR",
                                        "description": "Three-letter ISO currency code (e.g., 'EUR', 'USD'), required for create action. Default: 'EUR'.",
                                        "pattern": "^[A-Z]{3}$"
                                    },
                                    "phone": {
                                        "type": "string",
                                        "maxLength": 30,
                                        "description": "Customer's phone number"
                                    },
                                    "fax": {
                                        "type": "string",
                                        "maxLength": 30,
                                        "description": "Customer's fax number"
                                    },
                                    "mobile": {
                                        "type": "string",
                                        "maxLength": 30,
                                        "description": "Customer's mobile number"
                                    },
                                    "email": {
                                        "type": "string",
                                        "maxLength": 75,
                                        "format": "email",
                                        "description": "Customer's email address"
                                    },
                                    "homepage": {
                                        "type": "string",
                                        "maxLength": 100,
                                        "format": "uri",
                                        "description": "Customer's website URL"
                                    },
                                    "color": {
                                        "type": "string",
                                        "description": "The assigned display color for the customer in HTML hex format (e.g., #dd1d00). If left empty, a color might be auto-calculated."
                                    },
                                    "timezone": {
                                        "type": "string",
                                        "maxLength": 64,
                                        "description": "Timezone identifier (e.g., 'Europe/Berlin', 'America/New_York'), required for create action."
                                    },
                                    "language": {
                                        "type": "string",
                                        "maxLength": 35,
                                        "description": "Customer language for invoices and exports (e.g., 'de', 'en'). Requires Kimai 2.63+."
                                    },
                                    "invoiceEmail": {
                                        "type": "string",
                                        "format": "email",
                                        "description": "Email address invoices are sent to, if it differs from 'email'. Requires Kimai 2.63+."
                                    },
                                    "invoiceText": {
                                        "type": "string",
                                        "description": "Custom text to appear on invoices for this customer"
                                    },
                                    "invoiceTemplate": {
                                        "type": "string",
                                        "format": "App\\Entity\\InvoiceTemplate id",
                                        "description": "ID of the invoice template to use for this customer"
                                    },
                                    "teams": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                        "description": "IDs of the teams that get access to the customer. Kimai binds this field on create only; on update it is rejected as an extra field, use the team_access tool instead."
                                    },
                                    **_budget_schema(),
                                    "metaFields": _meta_fields_schema("customer")
                                },
                                "additionalProperties": False
                            }
                        },
                        "required": ["data"]
                    }
                },
                {
                    "if": {
                        "properties": {
                            "type": {"const": "project"},
                            "action": {"enum": ["create", "update"]}
                        }
                    },
                    "then": {
                        "properties": {
                            "data": {
                                "type": "object",
                                "description": "Data structure required for creating or updating a 'project' entity.",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "The official or internal name of the project, required for create action.",
                                        "minLength": 2,
                                        "maxLength": 150
                                    },
                                    "number": {
                                        "type": "string",
                                        "maxLength": 10,
                                        "description": "An internal tracking number or code for the project."
                                    },
                                    "comment": {
                                        "type": "string",
                                        "description": "Any additional notes or descriptive comments regarding the project."
                                    },
                                    "invoiceText": {
                                        "type": "string",
                                        "description": "Custom text that should appear on invoices generated for this project."
                                    },
                                    "orderNumber": {
                                        "type": "string",
                                        "maxLength": 50,
                                        "description": "The client's purchase order number or internal order reference for the project."
                                    },
                                    "orderDate": {
                                        "type": "string",
                                        "description": "The date when the project was ordered. Use YYYY-MM-DD for action=create and YYYY-MM-DDTHH:MM:SS for action=update (see 'start'). Times are not stored."
                                    },
                                    "start": {
                                        "type": "string",
                                        "description": "The official start date of the project. Timesheets cannot be recorded before this date. NOTE: the accepted format differs per action - action=create takes YYYY-MM-DD, action=update requires the full YYYY-MM-DDTHH:MM:SS form and answers 'Please enter a valid date.' to a date-only value. Kimai binds the two forms with different date formats (ProjectController: DATE_ONLY_FORMAT on POST, HTML5 DATE_FORMAT on PATCH); this asymmetry exists on projects only."
                                    },
                                    "end": {
                                        "type": "string",
                                        "description": "The projected or actual end date of the project. Timesheets cannot be recorded after this date. Same per-action format split as 'start': YYYY-MM-DD to create, YYYY-MM-DDTHH:MM:SS to update."
                                    },
                                    "lockedUntil": {
                                        "type": "string",
                                        "description": "Lock date (Kimai 2.66+). Timesheets beginning on or before this calendar day cannot be created, edited, stopped, restarted, duplicated or deleted in this project - admins included; Kimai answers 403 or 'The project is locked until ...'. Compared by day, independent of timezones. Same per-action format split as 'start': YYYY-MM-DD to create, YYYY-MM-DDTHH:MM:SS to update. Send an empty string to clear the lock. Rejected by Kimai < 2.66 ('This form should not contain extra fields.')."
                                    },
                                    "customer": {
                                        "description": "The unique ID of the customer to whom this project belongs, required for create action.",
                                        "type": "integer"
                                    },
                                    "color": {
                                        "description": "The assigned display color for the project in HTML hex format (e.g., #dd1d00). If left empty, a color might be auto-calculated.",
                                        "type": "string"
                                    },
                                    "globalActivities": {
                                        "type": "boolean",
                                        "description": "Indicates whether this project allows the booking of globally defined activities.",
                                        "default": True
                                    },
                                    "visible": {
                                        "type": "boolean",
                                        "description": "Controls the visibility of the project. If False, timesheets usually cannot be recorded against it.",
                                        "default": True
                                    },
                                    "billable": {
                                        "type": "boolean",
                                        "default": True,
                                        "description": "Determines if time and expenses recorded against this project are considered billable to the customer."
                                    },
                                    "teams": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                        "description": "IDs of the teams that get access to the project. Kimai binds this field on create only; on update it is rejected as an extra field, use the team_access tool instead."
                                    },
                                    **_budget_schema(),
                                    "metaFields": _meta_fields_schema("project")
                                },
                                "additionalProperties": False
                            }
                        },
                        "required": ["data"]
                    },
                },
                {
                    "if": {
                        "properties": {
                            "type": {"const": "activity"},
                            "action": {"enum": ["create", "update"]}
                        }
                    },
                    "then": {
                        "properties": {
                            "data": {
                                "type": "object",
                                "description": "Data structure required for creating or updating an 'activity' entity.",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "The name of the activity, required for create action.",
                                        "minLength": 2,
                                        "maxLength": 150
                                    },
                                    "number": {
                                        "type": "string",
                                        "maxLength": 10,
                                        "description": "An internal tracking number or code for the activity."
                                    },
                                    "comment": {
                                        "type": "string",
                                        "description": "Any additional notes or descriptive comments regarding the activity."
                                    },
                                    "invoiceText": {
                                        "type": "string",
                                        "description": "Custom text that should appear on invoices generated for this activity."
                                    },
                                    "project": {
                                        "type": "integer",
                                        "description": "ID of the project this activity belongs to. Omit for a global activity. Kimai binds this field on create, and on update only for activities that are not global."
                                    },
                                    "teams": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                        "description": "IDs of the teams that get access to the activity. Kimai binds this field on create only; on update it is rejected as an extra field, use the team_access tool instead."
                                    },
                                    "color": {
                                        "type": "string",
                                        "description": "The assigned display color for the activity in HTML hex format (e.g., #dd1d00). If left empty, a color might be auto-calculated."
                                    },
                                    "visible": {
                                        "type": "boolean",
                                        "description": "Controls the visibility of the activity. If False, timesheets usually cannot be recorded against it.",
                                        "default": True
                                    },
                                    "billable": {
                                        "type": "boolean",
                                        "default": True,
                                        "description": "Determines if time recorded against this activity is considered billable."
                                    },
                                    **_budget_schema(),
                                    "metaFields": _meta_fields_schema("activity")
                                },
                                "additionalProperties": False
                            }
                        },
                        "required": ["data"]
                    },
                },
                *_user_branches(),
                *_team_tag_invoice_branches(),
                {
                    "if": {
                        "properties": {
                            "action": {"enum": ["create", "update"]}
                        }
                    },
                    "else": {
                        "properties": {
                            "data": {"not": {}}  # `data` should not be present / empty if action is not create / update
                        }
                    }
                },
                {
                    "if": {
                        "properties": {
                            "action": {"enum": ["get", "update", "delete"]}
                        }
                    },
                    "then": {
                        "required": ["id"]
                    }
                }
            ]

        }
    )


async def handle_entity(client: KimaiClient, **params) -> list[TextContent]:
    """Handle consolidated entity operations."""
    entity_type = params.get("type")
    action = params.get("action")
    entity_id = params.get("id")
    filters = params.get("filters", {})
    data = params.get("data", {})

    # Route to appropriate handler
    handlers = {
        "project": ProjectEntityHandler(client),
        "activity": ActivityEntityHandler(client),
        "customer": CustomerEntityHandler(client),
        "user": UserEntityHandler(client),
        "team": TeamEntityHandler(client),
        "tag": TagEntityHandler(client),
        "invoice": InvoiceEntityHandler(client),
        "holiday": HolidayEntityHandler(client)
    }

    handler = handlers.get(entity_type)
    if not handler:
        raise ToolError(
            f"Error: Unknown entity type '{entity_type}'. Valid types: {', '.join(handlers.keys())}"
        )

    # Execute action - errors propagate to the central handler in server.py
    if action == "list":
        content = await handler.list(filters)
        # The filters object is shared by all types; say which keys had no
        # effect instead of returning an unfiltered list as if it were filtered.
        ignored = sorted(set(filters) - handler.list_filters)
        if ignored:
            content.append(TextContent(
                type="text",
                text=f"Note: ignored filter(s) that do not apply to type={entity_type}: {', '.join(ignored)}",
            ))
        return content
    elif action == "get":
        if not entity_id:
            raise ToolError("Error: 'id' parameter is required for get action")
        return await handler.get(entity_id)
    elif action == "create":
        if not data:
            raise ToolError("Error: 'data' parameter is required for create action")
        return await handler.create(data)
    elif action == "update":
        if not entity_id:
            raise ToolError("Error: 'id' parameter is required for update action")
        if not data:
            raise ToolError("Error: 'data' parameter is required for update action")
        return await handler.update(entity_id, data)
    elif action == "delete":
        if not entity_id:
            raise ToolError("Error: 'id' parameter is required for delete action")
        return await handler.delete(entity_id)
    elif action == "lock_month":
        if entity_type != "user":
            raise ToolError("Error: 'lock_month' action is only available for user entities")
        month = params.get("month")
        if not month:
            raise ToolError("Error: 'month' parameter is required for lock_month action")

        # Determine user IDs to process
        user_ids = params.get("ids", [])
        user_scope = params.get("user_scope")

        if user_scope == "all":
            return await handler.lock_month_bulk(None, month, all_users=True)
        elif user_ids:
            return await handler.lock_month_bulk(user_ids, month)
        elif entity_id:
            return await handler.lock_month(entity_id, month)
        else:
            raise ToolError("Error: 'id', 'ids', or 'user_scope=all' is required for lock_month action")
    elif action == "unlock_month":
        if entity_type != "user":
            raise ToolError("Error: 'unlock_month' action is only available for user entities")
        month = params.get("month")
        if not month:
            raise ToolError("Error: 'month' parameter is required for unlock_month action")

        # Determine user IDs to process
        user_ids = params.get("ids", [])
        user_scope = params.get("user_scope")

        if user_scope == "all":
            return await handler.unlock_month_bulk(None, month, all_users=True)
        elif user_ids:
            return await handler.unlock_month_bulk(user_ids, month)
        elif entity_id:
            return await handler.unlock_month(entity_id, month)
        else:
            raise ToolError("Error: 'id', 'ids', or 'user_scope=all' is required for unlock_month action")
    elif action == "batch_delete":
        ids = params.get("ids", [])
        if not ids:
            raise ToolError("Error: 'ids' parameter is required for batch_delete action")
        return await _handle_batch_delete(handler, entity_type, ids)
    elif action == "set_preferences":
        if entity_type != "user":
            raise ToolError("Error: 'set_preferences' action is only available for user entities")
        preferences = params.get("preferences", [])
        if not preferences:
            raise ToolError("Error: 'preferences' parameter is required for set_preferences action")
        if not entity_id:
            raise ToolError("Error: 'id' parameter is required for set_preferences action")
        return await handler.set_preferences(entity_id, preferences)
    else:
        raise ToolError(
            f"Error: Unknown action '{action}'. Valid actions: list, get, create, update, delete, lock_month, unlock_month, batch_delete, set_preferences"
        )


async def _handle_batch_delete(handler: 'BaseEntityHandler', entity_type: str, ids: list[int]) -> list[TextContent]:
    """Batch delete multiple entities."""
    # Map entity types to client delete methods; anything else (user, unknown
    # types) is rejected below.
    delete_methods = {
        "project": handler.client.delete_project,
        "activity": handler.client.delete_activity,
        "customer": handler.client.delete_customer,
        "team": handler.client.delete_team,
        "tag": handler.client.delete_tag,
        "holiday": handler.client.delete_public_holiday,
        "invoice": handler.client.delete_invoice,  # Kimai 2.66+
    }

    delete_method = delete_methods.get(entity_type)
    if not delete_method:
        raise ToolError(
            f"Error: batch_delete is not supported for {entity_type} entities"
        )

    async def delete_one(id: int) -> int:
        await delete_method(id)
        return id

    success, failed = await execute_batch(ids, delete_one)
    result = format_batch_result("Delete", success, failed, f"{entity_type}s")
    return [TextContent(type="text", text=result)]


class BaseEntityHandler:
    """Base class for entity-specific handlers."""

    # Keys of the shared `filters` object that this type's list action passes on.
    list_filters: frozenset[str] = frozenset()

    def __init__(self, client: KimaiClient):
        self.client = client

    @staticmethod
    def _serialize_budget(entity) -> str:
        """Render the budget block shared by customers, projects and activities.

        Kimai sends 0 for "no budget", so only non-zero values are shown.

        The time budget is printed in hours *and* in the raw seconds Kimai
        sent, because those seconds are what an update takes back (a bare
        number in a duration *string* would be read as hours instead).
        """
        out = ""
        budget = getattr(entity, 'budget', None)
        if budget:
            budget_type = getattr(entity, 'budget_type', None)
            period = f" per {budget_type}" if budget_type else ""
            currency = getattr(entity, 'currency', None)
            amount = f"{budget} {currency}" if currency else f"{budget}"
            out += f"Budget: {amount}{period}\n"
        time_budget = getattr(entity, 'time_budget', None)
        if time_budget:
            out += f"Time Budget: {time_budget / 3600:.2f} hours ({time_budget} seconds)\n"
        return out

    @staticmethod
    def _serialize_teams(entity) -> str:
        """Render the teams that have access, which Kimai embeds as stubs."""
        teams = getattr(entity, 'teams', None)
        if not teams:
            return ""
        names = [t.name or f"ID {t.id}" for t in teams]
        return f"Teams: {', '.join(names)}\n"

    @staticmethod
    def _serialize_meta_fields(entity) -> str:
        """Render custom fields; items are MetaField models or plain dicts."""
        meta_fields = getattr(entity, 'meta_fields', None)
        if not meta_fields:
            return ""
        result = "Meta Fields:\n"
        for mf in meta_fields:
            name = mf.name if hasattr(mf, 'name') else mf.get('name', 'Unknown')
            value = mf.value if hasattr(mf, 'value') else mf.get('value', '')
            result += f"  - {name}: {value}\n"
        return result

    async def list(self, filters: dict) -> list[TextContent]:
        raise NotImplementedError

    async def get(self, id: int) -> builtins.list[TextContent]:
        raise NotImplementedError

    async def create(self, data: dict) -> builtins.list[TextContent]:
        raise NotImplementedError

    async def update(self, id: int, data: dict) -> builtins.list[TextContent]:
        raise NotImplementedError

    async def delete(self, id: int) -> builtins.list[TextContent]:
        raise NotImplementedError


class ProjectEntityHandler(BaseEntityHandler):
    """Handler for project operations."""

    list_filters = frozenset({
        "customer", "customers", "term", "visible", "order", "order_by",
        "begin", "end", "ignore_dates", "global_activities",
    })

    def serialize_project(self, project) -> str:
        result = f"Project: {project.name} (ID: {project.id})\n"
        customer_label = getattr(project, 'parent_title', None)
        result += (
            f"Customer: {customer_label} (ID: {project.customer})\n"
            if customer_label else
            f"Customer ID: {project.customer if project.customer else 'None'}\n"
        )
        result += f"Status: {'Active' if project.visible else 'Inactive'}\n"
        result += f"Billable: {'Yes' if project.billable else 'No'}\n"
        if hasattr(project, 'global_activities'):
            result += f"Global Activities: {'Yes' if project.global_activities else 'No'}\n"
        if getattr(project, 'number', None):
            result += f"Number: {project.number}\n"
        if getattr(project, 'color', None):
            result += f"Color: {project.color}\n"

        # Project timeframe and order data
        start = getattr(project, 'start', None)
        end = getattr(project, 'end', None)
        if start or end:
            result += (
                f"Timeframe: {start.date() if start else 'open'}"
                f" - {end.date() if end else 'open'}\n"
            )
        if getattr(project, 'order_number', None):
            result += f"Order Number: {project.order_number}\n"
        if getattr(project, 'order_date', None):
            result += f"Order Date: {project.order_date.date()}\n"
        if getattr(project, 'locked_until', None):
            result += f"Locked Until: {project.locked_until} (timesheets up to this day are read-only)\n"
        result += self._serialize_budget(project)
        result += self._serialize_teams(project)

        if getattr(project, 'comment', None):
            result += f"Comment: {project.comment}\n"
        result += self._serialize_meta_fields(project)
        result += "\n"
        return result

    async def list(self, filters: dict) -> list[TextContent]:
        project_filter = ProjectFilter(
            customer=filters.get("customer"),
            customers=filters.get("customers"),
            term=filters.get("term"),
            visible=filters.get("visible", 1),
            order=filters.get("order"),
            order_by=filters.get("order_by"),
            # Kimai's `start`/`end` each mean "running on that day".
            start=filters.get("begin"),
            end=filters.get("end"),
            ignore_dates="1" if filters.get("ignore_dates") else None,
            global_activities=filters.get("global_activities"),
        )
        projects = await self.client.get_projects(project_filter)

        result = f"Found {len(projects)} projects\n\n"
        for project in projects:
            result += self.serialize_project(project)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> builtins.list[TextContent]:
        project = await self.client.get_project(id)

        result = self.serialize_project(project)

        return [TextContent(type="text", text=result)]

    async def create(self, data: dict) -> builtins.list[TextContent]:
        # Validate required fields explicitly to provide a clear error before calling the API
        required_fields = ["name", "customer"]
        missing = [field for field in required_fields if not data.get(field)]
        if missing:
            raise ToolError(
                f"Error: Missing required project fields: {', '.join(missing)}"
            )
        form = ProjectEditForm(**data)
        project = await self.client.create_project(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_project(project)
        )]

    async def update(self, id: int, data: dict) -> builtins.list[TextContent]:
        form = ProjectEditForm(**data)
        project = await self.client.update_project(id, form)
        return [TextContent(
            type="text",
            text="Updated " + self.serialize_project(project)
        )]

    async def delete(self, id: int) -> builtins.list[TextContent]:
        await self.client.delete_project(id)
        return [TextContent(type="text", text=f"Deleted project ID {id}")]


class ActivityEntityHandler(BaseEntityHandler):
    """Handler for activity operations."""

    list_filters = frozenset({"project", "projects", "visible", "globals", "term", "order", "order_by"})

    def serialize_activity(self, activity) -> str:
        result = f"Activity: {activity.name} (ID: {activity.id})\n"
        project_label = getattr(activity, 'parent_title', None)
        if project_label:
            result += f"Project: {project_label} (ID: {activity.project})\n"
        elif activity.project:
            result += f"Project ID: {activity.project}\n"
        else:
            result += "Project: none (global activity)\n"
        result += f"Status: {'Active' if activity.visible else 'Inactive'}\n"
        result += f"Billable: {'Yes' if activity.billable else 'No'}\n"
        if getattr(activity, 'number', None):
            result += f"Number: {activity.number}\n"
        if getattr(activity, 'color', None):
            result += f"Color: {activity.color}\n"
        result += self._serialize_budget(activity)
        result += self._serialize_teams(activity)
        if getattr(activity, 'comment', None):
            result += f"Comment: {activity.comment}\n"
        result += self._serialize_meta_fields(activity)
        result += "\n"
        return result

    async def list(self, filters: dict) -> list[TextContent]:
        activity_filter = ActivityFilter(
            project=filters.get("project"),
            projects=filters.get("projects"),
            visible=filters.get("visible", 1),
            globals=filters.get("globals"),
            term=filters.get("term"),
            order=filters.get("order"),
            order_by=filters.get("order_by")
        )
        activities = await self.client.get_activities(activity_filter)

        result = f"Found {len(activities)} activities\n\n"
        for activity in activities:
            result += self.serialize_activity(activity)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> builtins.list[TextContent]:
        activity = await self.client.get_activity(id)

        result = self.serialize_activity(activity)

        return [TextContent(type="text", text=result)]

    async def create(self, data: dict) -> builtins.list[TextContent]:
        form = ActivityEditForm(**data)
        activity = await self.client.create_activity(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_activity(activity)
        )]

    async def update(self, id: int, data: dict) -> builtins.list[TextContent]:
        form = ActivityEditForm(**data)
        activity = await self.client.update_activity(id, form)
        return [TextContent(
            type="text",
            text="Updated " + self.serialize_activity(activity)
        )]

    async def delete(self, id: int) -> builtins.list[TextContent]:
        await self.client.delete_activity(id)
        return [TextContent(type="text", text=f"Deleted activity ID {id}")]


class CustomerEntityHandler(BaseEntityHandler):
    """Handler for customer operations."""

    list_filters = frozenset({"visible", "term", "order", "order_by", "full"})

    def serialize_customer(self, customer: Customer) -> str:
        result = f"Customer: {customer.name} (ID: {customer.id})\n"
        result += f"Status: {'Active' if customer.visible else 'Inactive'}\n"
        result += f"Billable: {'Yes' if customer.billable else 'No'}\n"

        # Optional core fields
        if getattr(customer, 'country', None):
            result += f"Country: {customer.country}\n"
        if getattr(customer, 'currency', None):
            result += f"Currency: {customer.currency}\n"
        if getattr(customer, 'timezone', None):
            result += f"Timezone: {customer.timezone}\n"

        # Optional identifiers and visuals
        if getattr(customer, 'number', None):
            result += f"Number: {customer.number}\n"
        if getattr(customer, 'color', None):
            result += f"Color: {customer.color}\n"

        # Optional contact/company details
        if getattr(customer, 'phone', None):
            result += f"Phone: {customer.phone}\n"
        if getattr(customer, 'fax', None):
            result += f"Fax: {customer.fax}\n"
        if getattr(customer, 'mobile', None):
            result += f"Mobile: {customer.mobile}\n"
        if getattr(customer, 'email', None):
            result += f"Email: {customer.email}\n"
        if getattr(customer, 'homepage', None):
            result += f"Homepage: {customer.homepage}\n"
        if getattr(customer, 'company', None):
            result += f"Company: {customer.company}\n"
        if getattr(customer, 'contact', None):
            result += f"Contact: {customer.contact}\n"

        if getattr(customer, 'language', None):
            result += f"Language: {customer.language}\n"

        # Address: structured fields (Kimai 2.62+ detail set) with the legacy
        # unstructured 'address' as fallback.
        address_lines = [
            getattr(customer, attr, None)
            for attr in ('address_line1', 'address_line2', 'address_line3')
        ]
        city_line = " ".join(
            part for part in (getattr(customer, 'post_code', None), getattr(customer, 'city', None))
            if part
        )
        address_parts = [part for part in [*address_lines, city_line] if part]
        legacy_address = getattr(customer, 'address', None)
        if address_parts:
            result += "Address: " + ", ".join(address_parts) + "\n"
            # Kimai stores the old single-line field separately, so both can be set.
            if legacy_address:
                result += f"Legacy Address: {legacy_address}\n"
        elif legacy_address:
            result += f"Address: {legacy_address}\n"

        # Invoicing / billing
        if getattr(customer, 'vat_id', None):
            result += f"VAT ID: {customer.vat_id}\n"
        if getattr(customer, 'invoice_email', None):
            result += f"Invoice Email: {customer.invoice_email}\n"
        if getattr(customer, 'buyer_reference', None):
            result += f"Buyer Reference: {customer.buyer_reference}\n"
        result += self._serialize_budget(customer)
        result += self._serialize_teams(customer)

        if getattr(customer, 'comment', None):
            result += f"Comment: {customer.comment}\n"
        result += self._serialize_meta_fields(customer)
        result += "\n"

        return result

    async def list(self, filters: dict) -> list[TextContent]:
        customer_filter = CustomerFilter(
            visible=filters.get("visible", 1),
            term=filters.get("term"),
            order=filters.get("order"),
            order_by=filters.get("order_by"),
            full=1 if filters.get("full") else None,
        )
        customers = await self.client.get_customers(customer_filter)

        result = f"Found {len(customers)} customers\n\n"
        for customer in customers:
            result += self.serialize_customer(customer)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> builtins.list[TextContent]:
        customer = await self.client.get_customer(id)

        result = self.serialize_customer(customer)

        return [TextContent(type="text", text=result)]

    async def create(self, data: dict) -> builtins.list[TextContent]:
        # Validate required fields explicitly to provide a clear error before calling the API
        required_fields = ["name", "country", "currency", "timezone"]
        missing = [field for field in required_fields if not data.get(field)]
        if missing:
            raise ToolError(
                f"Error: Missing required customer fields: {', '.join(missing)}"
            )

        form = CustomerEditForm(**data)
        customer = await self.client.create_customer(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_customer(customer)
        )]

    async def update(self, id: int, data: dict) -> builtins.list[TextContent]:
        form = CustomerEditForm(**data)
        customer = await self.client.update_customer(id, form)
        return [TextContent(
            type="text",
            text="Updated " + self.serialize_customer(customer)
        )]

    async def delete(self, id: int) -> builtins.list[TextContent]:
        await self.client.delete_customer(id)
        return [TextContent(type="text", text=f"Deleted customer ID {id}")]


def format_user(user) -> str:
    """Render a ``User``; roles, supervisor, teams and preferences when it is a ``UserEntity``.

    Shared by ``entity type=user`` and ``user_current``. ``initials`` is not
    shown: Kimai derives it from the display name.
    """
    result = f"User: {user.username} (ID: {user.id})\n"
    result += f"Name: {user.alias or 'Not set'}\n"
    result += f"Title: {user.title or 'Not set'}\n"
    result += f"Status: {'Active' if user.enabled else 'Inactive'}\n"
    if user.system_account:
        result += "System Account: Yes\n"
    for label, value in (
        ("Email", user.email),
        ("Account Number", user.account_number),
        ("Language", user.language),
        ("Locale", user.locale),
        ("Timezone", user.timezone),
        ("Color", user.color),
        ("Avatar", user.avatar),
    ):
        if value:
            result += f"{label}: {value}\n"

    roles = getattr(user, 'roles', None)
    if roles:
        result += f"Roles: {', '.join(roles)}\n"
    supervisor = getattr(user, 'supervisor', None)
    if supervisor:
        result += f"Supervisor: {supervisor.alias or supervisor.username} (ID: {supervisor.id})\n"

    # Memberships carry the team-lead flag; `teams` is the same set without it.
    memberships = getattr(user, 'memberships', None)
    teams = getattr(user, 'teams', None)
    if memberships:
        labels = []
        for membership in memberships:
            team = membership.get('team') or {}
            lead = ", team lead" if membership.get('teamlead') else ""
            labels.append(f"{team.get('name')} (ID: {team.get('id')}{lead})")
        result += f"Teams: {', '.join(labels)}\n"
    elif teams:
        result += f"Teams: {', '.join(f'{t.name} (ID: {t.id})' for t in teams)}\n"

    preferences = getattr(user, 'preferences', None)
    if preferences:
        result += "Preferences:\n"
        for pref in preferences:
            result += f"  - {pref.get('name')}: {pref.get('value')}\n"
    return result


class UserEntityHandler(BaseEntityHandler):
    """Handler for user operations."""

    list_filters = frozenset({"visible", "term", "order", "order_by"})

    def serialize_user(self, user) -> str:
        return format_user(user) + "\n"

    async def list(self, filters: dict) -> list[TextContent]:
        # Validated like the other types' filters, before Kimai answers 400.
        user_filter = UserFilter(
            visible=filters.get("visible", 1),
            term=filters.get("term"),
            order_by=filters.get("order_by"),
            order=filters.get("order"),
        )
        users = await self.client.get_users(
            visible=user_filter.visible,
            term=user_filter.term,
            order_by=user_filter.order_by,
            order=user_filter.order,
        )

        result = f"Found {len(users)} users\n\n"
        for user in users:
            result += self.serialize_user(user)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> builtins.list[TextContent]:
        user = await self.client.get_user_extended(id)

        result = self.serialize_user(user)

        return [TextContent(type="text", text=result)]

    async def create(self, data: dict) -> builtins.list[TextContent]:
        form = UserCreateForm(**data)
        user = await self.client.create_user(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_user(user)
        )]

    async def update(self, id: int, data: dict) -> builtins.list[TextContent]:
        form = UserEditForm(**data)
        user = await self.client.update_user(id, form)
        return [TextContent(
            type="text",
            text="Updated " + self.serialize_user(user)
        )]

    async def delete(self, id: int) -> builtins.list[TextContent]:
        raise ToolError(
            "Error: Users cannot be deleted. Use update with enabled=false to deactivate."
        )

    async def lock_month(self, user_id: int, month: str) -> builtins.list[TextContent]:
        """Lock working time months for a user."""
        await self.client.lock_work_contract_month(user_id, month)
        return [TextContent(
            type="text",
            text=f"Locked working time months up to and including {month} for user ID {user_id}"
        )]

    async def _resolve_all_user_ids(self) -> builtins.list[int]:
        """Resolve IDs of all accessible active users (teams first, get_users fallback)."""
        users = await resolve_accessible_users(self.client)
        return [u.id for u in users if getattr(u, 'enabled', True)]

    async def lock_month_bulk(self, user_ids: builtins.list[int], month: str, all_users: bool = False) -> builtins.list[TextContent]:
        """Lock working time months for multiple users."""
        if all_users:
            try:
                user_ids = await self._resolve_all_user_ids()
            except Exception as e:
                if isinstance(e, KimaiAPIError) and e.status_code == 403:
                    raise ToolError(
                        "Error: You don't have permission to access all users.\n\n"
                        "This requires either:\n"
                        "- System Administrator role, or\n"
                        "- Being a team lead (to access team members)\n\n"
                        "Use 'ids' parameter to specify specific user IDs instead."
                    )
                raise

        async def lock_one(uid: int) -> int:
            await self.client.lock_work_contract_month(uid, month)
            return uid

        success, failed = await execute_batch(user_ids, lock_one)

        result = f"Locked month {month} for {len(success)} users"
        if failed:
            result += f", {len(failed)} failed:\n"
            for uid, error in failed:
                result += f"  - User {uid}: {error}\n"

        return [TextContent(type="text", text=result)]

    async def unlock_month(self, user_id: int, month: str) -> builtins.list[TextContent]:
        """Unlock working time months for a user."""
        await self.client.unlock_work_contract_month(user_id, month)
        return [TextContent(
            type="text",
            text=f"Unlocked working time months from {month} onwards for user ID {user_id}"
        )]

    async def unlock_month_bulk(self, user_ids: builtins.list[int], month: str, all_users: bool = False) -> builtins.list[TextContent]:
        """Unlock working time months for multiple users."""
        if all_users:
            try:
                user_ids = await self._resolve_all_user_ids()
            except Exception as e:
                if isinstance(e, KimaiAPIError) and e.status_code == 403:
                    raise ToolError(
                        "Error: You don't have permission to access all users.\n\n"
                        "This requires either:\n"
                        "- System Administrator role, or\n"
                        "- Being a team lead (to access team members)\n\n"
                        "Use 'ids' parameter to specify specific user IDs instead."
                    )
                raise

        async def unlock_one(uid: int) -> int:
            await self.client.unlock_work_contract_month(uid, month)
            return uid

        success, failed = await execute_batch(user_ids, unlock_one)

        result = f"Unlocked month {month} for {len(success)} users"
        if failed:
            result += f", {len(failed)} failed:\n"
            for uid, error in failed:
                result += f"  - User {uid}: {error}\n"

        return [TextContent(type="text", text=result)]

    async def set_preferences(self, user_id: int, preferences: builtins.list[dict]) -> builtins.list[TextContent]:
        """Set user preferences (e.g., work contract settings).

        Args:
            user_id: The user ID
            preferences: List of {"name": "...", "value": "..."} dicts

        Common work contract preferences:
            - work_contract_type: "week" or "day"
            - hours_per_week: Total weekly hours in seconds (144000 = 40h)
            - work_monday..work_sunday: Daily hours in seconds (28800 = 8h)
            - work_days_week: Work days (e.g., "1,2,3,4,5")
            - holidays: Vacation days per year
            - public_holiday_group: Holiday group ID
            - work_start_day/work_last_day: Contract period (YYYY-MM-DD)

        Aliases supported: vacation_days -> holidays, weekly_hours -> hours_per_week
        """
        # Normalize preference names using aliases
        normalized_preferences = []
        for pref in preferences:
            normalized_pref = pref.copy()
            normalized_pref["name"] = normalize_preference_name(pref["name"])
            normalized_preferences.append(normalized_pref)

        try:
            user = await self.client.update_user_preferences(user_id, normalized_preferences)
        except KimaiAPIError as e:
            if e.status_code == 404:
                # Work Contract not configured for this user.
                # Kimai >= 2.61.0 (PR #5894) auto-initializes work-contract preferences via
                # the API, so this 404 should only occur on older servers (< 2.61.0).
                # Fetch user to get username for the UI fallback URL.
                try:
                    from urllib.parse import quote
                    user_info = await self.client.get_user_extended(user_id)
                    username = user_info.username if user_info else f"user-{user_id}"
                    username_encoded = quote(username, safe='')
                # Only used to build a nicer hint URL; a placeholder is fine.
                except Exception:  # noqa: BLE001
                    username_encoded = f"user-{user_id}"

                base_url = str(self.client.base_url).removesuffix('/api')

                # Note if the request included hours_per_week: auto-init (PR #5894) does NOT
                # register this preference, so a week-based contract may still 404 until the
                # contract mode is set to "week" first.
                pref_names = {p.get("name") for p in normalized_preferences}
                hours_per_week_hint = ""
                if "hours_per_week" in pref_names:
                    hours_per_week_hint = (
                        "\nNote: 'hours_per_week' is not auto-initialized. For a week-based "
                        "contract, set work_contract_type=\"week\" first (in its own request), "
                        "then set hours_per_week.\n"
                    )

                raise ToolError(
                    f"Error: Work Contract not configured for user {user_id}.\n\n"
                    f"The user preferences endpoint returned 404, which means the Work Contract "
                    f"has not been set up for this user in Kimai.\n\n"
                    f"Recommended fix: upgrade Kimai to the release with the work-contract "
                    f"auto-init fix (>= 2.61.0, PR #5894). The API then initializes "
                    f"work-contract preferences automatically and this call will succeed.\n\n"
                    f"Workaround for older Kimai (< 2.61.0): configure the work contract "
                    f"once in the Kimai UI, then retry via the API:\n"
                    f"  {base_url}/de/profile/{username_encoded}/contract\n"
                    f"{hours_per_week_hint}"
                )
            raise  # Re-raise other errors

        result = f"Updated preferences for {user.username} (ID: {user.id})\n\n"
        result += "Updated preferences:\n"
        for pref in preferences:
            result += f"  - {pref['name']}: {pref.get('value', '(empty)')}\n"

        if user.preferences:
            result += "\nAll current preferences:\n"
            for pref in user.preferences:
                result += f"  - {pref.get('name')}: {pref.get('value', '(empty)')}\n"

        return [TextContent(type="text", text=result)]


class TeamEntityHandler(BaseEntityHandler):
    """Handler for team operations."""

    def serialize_team(self, team) -> str:
        result = f"Team: {team.name} (ID: {team.id})\n"
        if team.color:
            result += f"Color: {team.color}\n"
        if team.members:
            result += f"\nMembers ({len(team.members)}):\n"
            for member in team.members:
                teamlead = " (Team Lead)" if member.teamlead else ""
                result += f"  - {member.user.username} (ID: {member.user.id}){teamlead}\n"
        # What team_access grant/revoke changes. Kimai sends these on a single
        # team only (Team_Entity), so a listing shows none of them.
        for label, items in (
            ("Customers", team.customers),
            ("Projects", team.projects),
            ("Activities", team.activities),
        ):
            if items:
                result += f"\n{label} with access ({len(items)}):\n"
                for item in items:
                    result += f"  - {item.name} (ID: {item.id})\n"
        result += "\n"
        return result

    async def list(self, filters: dict) -> list[TextContent]:
        teams = await self.client.get_teams()

        result = f"Found {len(teams)} teams\n\n"
        for team in teams:
            result += self.serialize_team(team)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> builtins.list[TextContent]:
        team = await self.client.get_team(id)

        result = self.serialize_team(team)

        return [TextContent(type="text", text=result)]

    async def create(self, data: dict) -> builtins.list[TextContent]:
        missing = [field for field in ("name", "members") if not data.get(field)]
        if missing:
            raise ToolError(f"Error: Missing required team fields: {', '.join(missing)}")
        form = TeamEditForm(**data)
        team = await self.client.create_team(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_team(team)
        )]

    async def update(self, id: int, data: dict) -> builtins.list[TextContent]:
        form = TeamEditForm(**data)
        team = await self.client.update_team(id, form)
        return [TextContent(
            type="text",
            text="Updated " + self.serialize_team(team)
        )]

    async def delete(self, id: int) -> builtins.list[TextContent]:
        await self.client.delete_team(id)
        return [TextContent(type="text", text=f"Deleted team ID {id}")]


class TagEntityHandler(BaseEntityHandler):
    """Handler for tag operations."""

    list_filters = frozenset({"name", "term"})

    def serialize_tag(self, tag) -> str:
        result = f"Tag: {tag.name} (ID: {tag.id})\n"
        visible_str = "Visible" if getattr(tag, 'visible', True) else "Hidden"
        result += f"Status: {visible_str}\n"
        if hasattr(tag, 'color') and tag.color:
            result += f"Color: {tag.color}\n"
        result += "\n"
        return result

    async def list(self, filters: dict) -> list[TextContent]:
        # Pass the name filter through to the API (server-side filtering)
        name = filters.get("name") or filters.get("term")
        tag_filter = TagFilter(name=name) if name else None
        tags = await self.client.get_tags_full(tag_filter)

        result = f"Found {len(tags)} tags\n\n"
        for tag in tags:
            result += self.serialize_tag(tag)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> builtins.list[TextContent]:
        raise ToolError(
            "Error: Tags don't support individual retrieval. Use list instead."
        )

    async def create(self, data: dict) -> builtins.list[TextContent]:
        form = TagEditForm(**data)
        tag = await self.client.create_tag(form)
        return [TextContent(
            type="text",
            text="Created " + self.serialize_tag(tag)
        )]

    async def update(self, id: int, data: dict) -> builtins.list[TextContent]:
        raise ToolError(
            "Error: Tags cannot be updated. Delete and recreate if needed."
        )

    async def delete(self, id: int) -> builtins.list[TextContent]:
        await self.client.delete_tag(id)
        return [TextContent(type="text", text=f"Deleted tag ID {id}")]


class InvoiceEntityHandler(BaseEntityHandler):
    """Handler for invoice operations."""

    list_filters = frozenset({"begin", "end", "customers", "status", "page", "size"})

    def serialize_invoice(self, invoice) -> str:
        result = f"Invoice: {invoice.invoice_number} (ID: {invoice.id})\n"
        customer = invoice.customer
        result += f"Customer: {customer.name} (ID: {customer.id})\n" if customer else "Customer: Unknown\n"
        if invoice.user:
            result += f"Created By: {invoice.user.alias or invoice.user.username} (ID: {invoice.user.id})\n"
        result += f"Status: {invoice.status}\n"
        if invoice.overdue is not None:
            result += f"Overdue: {'Yes' if invoice.overdue else 'No'}\n"
        currency = f" {invoice.currency}" if invoice.currency else ""
        result += f"Total: {invoice.total}{currency}\n"
        # `tax` is the amount, `vat` the rate the invoice template applied.
        result += f"Tax: {invoice.tax}{currency} (VAT rate: {invoice.vat}%)\n"
        result += f"Created: {invoice.created_at}\n"
        result += f"Due Days: {invoice.due_days}\n"
        if invoice.payment_date:
            result += f"Payment Date: {invoice.payment_date}\n"
        if invoice.comment:
            result += f"Comment: {invoice.comment}\n"
        if invoice.invoice_filename:
            result += f"File: {invoice.invoice_filename}\n"
        result += self._serialize_meta_fields(invoice)
        result += "\n"
        return result

    async def list(self, filters: dict) -> list[TextContent]:
        invoices = await self.client.get_invoices(InvoiceFilter(
            begin=filters.get("begin"),
            end=filters.get("end"),
            customers=filters.get("customers"),
            status=filters.get("status"),
            page=filters.get("page", 1),
            size=filters.get("size", 50)
        ))

        result = f"Found {len(invoices)} invoices\n\n"
        for invoice in invoices:
            result += self.serialize_invoice(invoice)

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> builtins.list[TextContent]:
        invoice = await self.client.get_invoice(id)

        return [TextContent(type="text", text=self.serialize_invoice(invoice))]

    async def create(self, data: dict) -> builtins.list[TextContent]:
        raise ToolError(
            "Error: Invoice creation is not supported through this API."
        )

    async def update(self, id: int, data: dict) -> builtins.list[TextContent]:
        # PATCH /api/invoices/{id} exists since Kimai 2.68 (#6184); older
        # instances answer 404/405.
        invoice = await self.client.update_invoice(id, InvoiceEditForm(**data))
        return [TextContent(type="text", text="Updated " + self.serialize_invoice(invoice))]

    async def delete(self, id: int) -> builtins.list[TextContent]:
        # DELETE /api/invoices/{id} exists since Kimai 2.66 (#6141) and needs
        # the delete_invoice permission; older instances answer 404/405.
        await self.client.delete_invoice(id)
        return [TextContent(
            type="text",
            text=f"Deleted invoice ID {id} including its generated document (Kimai 2.66+, permission delete_invoice)",
        )]


class HolidayEntityHandler(BaseEntityHandler):
    """Handler for holiday operations."""

    list_filters = frozenset({"begin", "end", "group"})

    async def list(self, filters: dict) -> list[TextContent]:
        holidays = await self.client.get_public_holidays(PublicHolidayFilter(
            begin=filters.get("begin"),
            end=filters.get("end"),
            group=filters.get("group"),
        ))

        result = f"Found {len(holidays)} holidays\n\n"
        for holiday in holidays:
            result += f"ID: {holiday.id} - {holiday.name}\n"
            result += f"  Date: {holiday.date}\n"
            if holiday.half_day:
                result += "  Half Day: Yes\n"
            group = holiday.public_holiday_group
            if group:
                result += f"  Group: {group.name} (ID: {group.id})\n"
            result += "\n"

        return [TextContent(type="text", text=result)]

    async def get(self, id: int) -> builtins.list[TextContent]:
        raise ToolError(
            "Error: Holidays don't support individual retrieval. Use list instead."
        )

    async def create(self, data: dict) -> builtins.list[TextContent]:
        raise ToolError(
            "Error: Holiday creation is managed by administrators."
        )

    async def update(self, id: int, data: dict) -> builtins.list[TextContent]:
        raise ToolError(
            "Error: Holiday updates are not supported through this API."
        )

    async def delete(self, id: int) -> builtins.list[TextContent]:
        await self.client.delete_public_holiday(id)
        return [TextContent(type="text", text=f"Deleted holiday ID {id}")]
