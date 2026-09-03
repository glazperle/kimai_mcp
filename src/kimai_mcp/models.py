"""Data models for Kimai API entities."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


class KimaiModel(BaseModel):
    """Base for every Kimai model: accepts both the field name and the alias.

    Kimai's API speaks camelCase, so aliased fields (``halfDay``, ``isFixed``,
    ``break``, ``orderBy``, ...) are what goes on the wire. Without
    ``populate_by_name`` the Python name is *silently ignored* on construction,
    so a handler passing ``half_day=True`` produced a form that serialized
    without ``halfDay`` at all and Kimai booked a full day. Accepting both
    spellings makes those calls mean what they say; ``by_alias=True`` on dump
    keeps the wire format unchanged.
    """

    model_config = ConfigDict(populate_by_name=True)


# Kimai's duration grammar, transcribed from the alternatives in
# `src/Validator/Constraints/Duration.php` (read at 2.65.0). The API form runs
# this constraint after the data transformer, so anything it rejects comes back
# as a 400 with no useful body - checking it here says what is actually wrong.
_DURATION_ALTERNATIVES = (
    r"-?[0-9]{1,}",                                          # decimal hours: "2", "90"
    r"-?[0-9]{1,}[,.]{1}[0-9]{1,}",                          # "1.5", "1,5"
    r"-?[0-9]{1,}:[0-9]{1,}:[0-9]{1,}",                      # "2:30:00"
    r"-?[0-9]{1,}:[0-9]{1,}",                                # "2:30"
    r"[0-9]{1,}[hHmMsS]{1}",                                 # "2h", "90m"
    r"[0-9]{1,}[hH]{1}[0-9]{1,}[mM]{1}",                     # "1h30m"
    r"[0-9]{1,}[hHmM]{1}[0-9]{1,}[sS]{1}",                   # "1h30s"
    r"[0-9]{1,}[mM]{1}[0-9]{1,}[sS]{1}",                     # "30m15s"
    r"[0-9]{1,}[hH]{1}[0-9]{1,}[mM]{1}[0-9]{1,}[sS]{1}",     # "1h30m15s"
)
_DURATION_PATTERN = re.compile("|".join(_DURATION_ALTERNATIVES))
_BARE_NUMBER = re.compile(r"-?[0-9]+")


def _normalize_duration(value: Any, field: str = "duration") -> Any:
    """Turn a duration input into a string Kimai reads as meant.

    Kimai is asymmetric about every ``DurationType`` field (``timeBudget`` on
    customers, projects and activities, ``break`` on timesheets) and the
    asymmetry costs a factor of 3600. A *response* carries the field as an
    integer number of **seconds**. A *request* binds it to ``DurationType``,
    whose transformer hands the value to ``Duration::parseDurationString()``
    (``src/Utils/Duration.php``, read at 2.65.0); there any bare number takes
    the ``is_numeric()`` branch into ``parseDecimalFormat()``, which multiplies
    by 3600. On the way in, a bare number is therefore **decimal hours**.
    Sending JSON ``7200`` instead of ``"7200"`` changes nothing: Symfony's
    ``Form::submit()`` casts every scalar to a string before any transformer
    sees it.

    So writing back what a ``get`` returned used to overshoot by 3600x: a
    two-hour budget reads as ``7200`` and would have been submitted as 7200
    *hours*; a 15-minute break sent as ``900`` became 900 hours. To keep a
    read/write round-trip honest:

    * an ``int`` is **seconds**, matching the read models, and is rendered as
      an unambiguous ``H:MM:SS`` colon duration before it goes on the wire;
    * a ``str`` keeps Kimai's documented duration format unchanged, where a
      bare number *is* hours: ``"2.0"``, ``"2h"`` and ``"2:00"`` all mean two
      hours. See https://www.kimai.org/documentation/duration-format.html
    * a bare-digit string such as ``"7200"`` is rejected. Kimai would read it
      as hours, but it is exactly what a caller produces by copying the
      seconds from a ``get`` and transporting them as a string, so it is the
      one spelling whose meaning cannot be trusted. Use the int, or add a
      unit.
    * ``""`` is passed through: Kimai's transformer maps it to 0 before the
      grammar check, so it clears the value. Surrounding whitespace is
      stripped, as Symfony's ``TrimListener`` would do anyway.
    """
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return value
        if _BARE_NUMBER.fullmatch(value):
            raise ValueError(
                f"{value!r} is ambiguous for {field}: Kimai would read it as "
                f"{value} HOURS, but a bare number is usually the seconds a "
                "read returned. Pass an int for seconds, or a duration with "
                'a unit: "2h", "2:00", "90m", "2:30:00".'
            )
        # Any other well-formed duration is Kimai's to interpret, not ours.
        if not _DURATION_PATTERN.fullmatch(value):
            raise ValueError(
                f"{value!r} is not a Kimai duration. Pass an int for seconds "
                '(7200), or a duration string: "2.0" / "2h" / "2:00" '
                '(all two hours), "90m", "2:30:00".'
            )
        return value

    # The two raises below stay ValueError rather than the TypeError ruff's
    # TRY004 asks for: pydantic turns a ValueError from a validator into the
    # ValidationError the tool layer reports, while a TypeError escapes it.
    #
    # bool is an int subclass; True would silently become one second.
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number of seconds, not a bool")  # noqa: TRY004

    if isinstance(value, float) and value.is_integer():
        value = int(value)

    if not isinstance(value, int):
        raise ValueError(  # noqa: TRY004
            f"{field} must be a whole number of seconds or a duration "
            f"string, got {type(value).__name__} {value!r}"
        )

    sign = "-" if value < 0 else ""
    hours, rest = divmod(abs(value), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{sign}{hours}:{minutes:02d}:{seconds:02d}"


def _normalize_time_budget(value: Any) -> Any:
    return _normalize_duration(value, "timeBudget")


def _normalize_break(value: Any) -> Any:
    return _normalize_duration(value, "break")


# What the *EditForm classes accept for `timeBudget` and `break`. Always a
# duration string once validated, so `model_dump()` puts the wire format on
# the request.
TimeBudget = Annotated[str | None, BeforeValidator(_normalize_time_budget)]
BreakDuration = Annotated[str | None, BeforeValidator(_normalize_break)]


class AccessTokenInfo(KimaiModel):
    """Metadata of a personal API token.

    Served by the ``ApiTokenBundle`` plugin (see ``kimai-plugin/ApiTokenBundle``);
    core Kimai has no endpoint that lists or creates access tokens.
    """

    id: int
    name: str | None = None
    last_usage: str | None = Field(None, alias="lastUsage")
    expires_at: str | None = Field(None, alias="expiresAt")


class AccessTokenCreated(AccessTokenInfo):
    """A freshly created API token - ``token`` is only ever returned once."""

    token: str


class User(KimaiModel):
    """User model (serializer group ``Default``).

    ``apiToken`` and ``color-safe`` are also on the wire and deliberately not
    modelled: the first is a UI flag whose name invites confusion with a
    credential, the second is only ``color`` with a fallback applied.
    """

    id: int
    username: str
    alias: str | None = None
    title: str | None = None
    enabled: bool = False
    color: str | None = None
    email: str | None = None
    account_number: str | None = Field(None, alias="accountNumber")
    avatar: str | None = None
    system_account: bool | None = Field(None, alias="systemAccount")
    initials: str | None = None
    language: str | None = None
    locale: str | None = None
    timezone: str | None = None


class MetaField(KimaiModel):
    """Meta field model."""
    name: str
    value: str | None = None


class TeamRef(KimaiModel):
    """A team as embedded in customer/project/activity payloads.

    Kimai serializes only a stub there (``id``, ``name``, ``color``), not the
    full team with members, so this is intentionally not the ``Team`` model:
    that one would recurse (team -> customers -> teams).
    """

    id: int | None = None
    name: str | None = None
    color: str | None = None


class Customer(KimaiModel):
    """Customer model.

    Which fields Kimai actually sends depends on the serializer group of the
    endpoint (verified against `src/Entity/Customer.php` at 2.65.0), so every
    field beyond id/name is optional:

    * ``Default`` (every response, including a plain listing): the block below
      up to ``metaFields``, ``language`` among them.
    * ``Customer_Details`` (listing with ``full=1``, Kimai 2.62+): ``vatId``
      and the structured address.
    * ``Customer_Entity`` (get/create/update only): the details above plus
      ``contact``, ``address``, ``email``, ``invoiceEmail``, ``buyerReference``
      and the budget fields.
    """

    id: int
    name: str
    country: str | None = None
    currency: str | None = None
    timezone: str | None = None
    number: str | None = None
    comment: str | None = None
    visible: bool = True
    billable: bool = True
    color: str | None = None

    phone: str | None = None
    fax: str | None = None
    mobile: str | None = None
    homepage: str | None = None
    company: str | None = None

    language: str | None = None  # Kimai 2.63+ (kimai/kimai#5857)
    meta_fields: list[MetaField] | None = Field(None, alias="metaFields")

    # Customer_Details: listing with full=1, and every single-customer response
    vat_id: str | None = Field(None, alias="vatId")
    address_line1: str | None = Field(None, alias="addressLine1")
    address_line2: str | None = Field(None, alias="addressLine2")
    address_line3: str | None = Field(None, alias="addressLine3")
    post_code: str | None = Field(None, alias="postCode")
    city: str | None = None

    # Customer_Entity: get/create/update only
    contact: str | None = None
    address: str | None = None  # legacy unstructured address
    email: str | None = None
    invoice_email: str | None = Field(None, alias="invoiceEmail")  # Kimai 2.63+ (#5855)
    buyer_reference: str | None = Field(None, alias="buyerReference")
    budget: float | None = None
    time_budget: int | None = Field(None, alias="timeBudget")
    budget_type: str | None = Field(None, alias="budgetType")
    teams: list[TeamRef] | None = None


class Project(KimaiModel):
    """Project model.

    ``start``/``end``, the order fields and the budget are part of what Kimai
    sends for a project; a listing carries everything except the budget, which
    is ``Project_Entity`` only.
    """

    id: int
    name: str
    customer: int | None = None
    comment: str | None = None
    visible: bool = True
    billable: bool = True
    global_activities: bool = Field(True, alias="globalActivities")
    number: str | None = None
    color: str | None = None
    # Serializer group Default, so listings carry them too.
    meta_fields: list[MetaField] | None = Field(None, alias="metaFields")
    # Project timeframe and order data (listing and entity)
    start: datetime | None = None
    end: datetime | None = None
    order_date: datetime | None = Field(None, alias="orderDate")
    order_number: str | None = Field(None, alias="orderNumber")
    parent_title: str | None = Field(None, alias="parentTitle")  # customer name
    teams: list[TeamRef] | None = None
    # Project_Entity only
    budget: float | None = None
    time_budget: int | None = Field(None, alias="timeBudget")
    budget_type: str | None = Field(None, alias="budgetType")


class Activity(KimaiModel):
    """Activity model."""
    id: int
    name: str
    project: int | None = None
    comment: str | None = None
    visible: bool = True
    billable: bool = True
    number: str | None = None
    color: str | None = None
    # Serializer group Default, so listings carry them too.
    meta_fields: list[MetaField] | None = Field(None, alias="metaFields")
    parent_title: str | None = Field(None, alias="parentTitle")  # project name
    teams: list[TeamRef] | None = None
    # Activity_Entity only
    budget: float | None = None
    time_budget: int | None = Field(None, alias="timeBudget")
    budget_type: str | None = Field(None, alias="budgetType")


class TimesheetEntity(KimaiModel):
    """Timesheet as served by the ``Not_Expanded`` schemas.

    That is ``TimesheetCollection`` (``GET /timesheets``) and ``TimesheetEntity``
    (``GET /timesheets/{id}``, create, update), where ``activity``, ``project``
    and ``user`` are ids. The two ``Expanded`` endpoints send objects instead --
    see :class:`TimesheetExpanded`.
    """

    id: int | None = None
    activity: int
    project: int
    user: int | None = None
    tags: list[str] = []
    begin: datetime
    end: datetime | None = None
    duration: int | None = 0
    description: str | None = None
    rate: float | None = 0.0
    internal_rate: float | None = Field(None, alias="internalRate")
    fixed_rate: float | None = Field(None, alias="fixedRate")
    hourly_rate: float | None = Field(None, alias="hourlyRate")
    exported: bool = False
    billable: bool = True
    meta_fields: list[dict[str, Any]] | None = Field(None, alias="metaFields")
    break_duration: int | None = Field(None, alias="break")


class ProjectExpanded(Project):
    """Project whose ``customer`` is an object (serializer group ``Expanded``)."""

    customer: Customer | None = None


class ActivityExpanded(Activity):
    """Activity whose ``project`` is an object, customer included."""

    project: ProjectExpanded | None = None


class TimesheetExpanded(TimesheetEntity):
    """Timesheet as served by the ``Expanded`` schemas.

    ``GET /timesheets/active`` and ``GET /timesheets/recent`` are declared as
    ``TimesheetCollectionExpanded`` in Kimai's ``src/API/TimesheetController.php``.
    The ``Expanded`` serializer group replaces the relation ids with the full
    objects, and it does so recursively: the project carries its customer, and
    the activity carries a project which carries that customer again.

    Parsing those responses with :class:`TimesheetEntity` raises three
    ``int_type`` validation errors and loses the whole response (issue #24).
    """

    activity: ActivityExpanded
    project: ProjectExpanded
    user: User | None = None


class TimesheetEditForm(KimaiModel):
    """Timesheet edit form for creating/updating timesheets."""
    begin: datetime | None = None
    end: datetime | None = None
    project: int | None = None # Required for creation
    activity: int | None = None  # Required for creation
    description: str | None = None
    fixed_rate: float | None = Field(None, alias="fixedRate")
    hourly_rate: float | None = Field(None, alias="hourlyRate")
    user: int | None = None
    tags: str | None = None
    exported: bool | None = None
    billable: bool | None = None
    break_duration: BreakDuration = Field(None, alias="break")  # see _normalize_duration


class TimesheetFilter(KimaiModel):
    """Filters for timesheet queries."""
    user: str | None = None  # User ID or "all"
    users: list[int] | None = None
    customer: int | None = None
    customers: list[int] | None = None
    project: int | None = None
    projects: list[int] | None = None
    activity: int | None = None
    activities: list[int] | None = None
    page: int | None = None
    size: int | None = None
    tags: list[str] | None = None
    order_by: str | None = Field(None, alias="orderBy")  # id, begin, end, rate
    order: str | None = None  # ASC, DESC
    begin: str | datetime | None = None  # HTML5 date format (YYYY-MM-DD)
    end: str | datetime | None = None  # HTML5 date format (YYYY-MM-DD)
    exported: int | None = None  # 0=not exported, 1=exported
    active: int | None = None  # 0=stopped, 1=active
    billable: int | None = None  # 0=non-billable, 1=billable
    full: str | None = None  # 0|1|false|true
    term: str | None = None
    modified_after: str | datetime | None = Field(None, alias="modified_after")  # HTML5 date format


class ProjectFilter(KimaiModel):
    """Filters for project queries."""
    customer: int | None = None
    customers: list[int] | None = None
    visible: int | None = 1  # 1=visible, 2=hidden, 3=both
    start: str | None = None  # HTML5 date format (YYYY-MM-DD)
    end: str | None = None  # HTML5 date format (YYYY-MM-DD)
    ignore_dates: str | None = Field(None, alias="ignoreDates")
    global_activities: str | None = Field(None, alias="globalActivities")  # 0|1
    order: str | None = None  # ASC, DESC
    order_by: str | None = Field(None, alias="orderBy")  # id, name, customer
    term: str | None = None


class ActivityFilter(KimaiModel):
    """Filters for activity queries."""
    project: int | None = None
    projects: list[int] | None = None
    visible: int | None = 1  # 1=visible, 2=hidden, 3=all
    globals: str | None = None  # 0|1
    order_by: str | None = Field(None, alias="orderBy")  # id, name, project
    order: str | None = None  # ASC, DESC
    term: str | None = None


class CustomerFilter(KimaiModel):
    """Filters for customer queries."""
    visible: int | None = 1  # 1=visible, 2=hidden, 3=both
    order: str | None = None  # ASC, DESC
    order_by: str | None = Field(None, alias="orderBy")  # id, name
    term: str | None = None
    # Kimai 2.62+: 1 returns the full detail set (needs the 'details_customer'
    # permission; Kimai silently falls back to the short form without it).
    full: int | None = None


class ApiError(KimaiModel):
    """API error response."""
    message: str
    code: int | None = None


class Version(KimaiModel):
    """Kimai version information."""
    version: str
    version_id: int = Field(alias="versionId")
    copyright: str


# Absence models

class AbsenceForm(KimaiModel):
    """Form for creating absences."""
    half_day: bool | None = Field(None, alias="halfDay")
    duration: str | None = None  # Duration string format (e.g., "01:30")
    comment: str
    user: int | None = None  # User ID (requires permission, defaults to current user)
    date: str  # Date format YYYY-MM-DD
    end: str | None = None  # End date for multi-day absences
    type: Literal[
        "holiday", "time_off", "sickness", "sickness_child", "other", "parental", "unpaid_vacation"] = "other"


class Absence(KimaiModel):
    """Absence model matching API Absence2 schema."""
    id: int | None = None
    user: User
    date: datetime
    duration: int | None = None  # Duration in seconds according to API
    type: str = "other"
    status: str = "new"
    half_day: bool = Field(False, alias="halfDay")
    # Optional fields that might be present in responses
    comment: str | None = None
    end_date: datetime | None = Field(None, alias="endDate")


class AbsenceFilter(KimaiModel):
    """Filters for absence queries."""
    user: str | None = None
    begin: str | None = None  # HTML5 date format (YYYY-MM-DD)
    end: str | None = None  # HTML5 date format (YYYY-MM-DD)
    status: str | None = None  # approved, open, all


# Team models

class TeamMember(KimaiModel):
    """Team member model."""
    user: User
    teamlead: bool = False


class TeamEditForm(KimaiModel):
    """Form for creating/editing teams."""
    name: str
    color: str | None = None
    members: list[dict[str, Any]]  # List of {user: int, teamlead: bool}


class Team(KimaiModel):
    """Team model."""
    id: int | None = None
    name: str
    members: list[TeamMember] = []
    customers: list[Customer] = []
    projects: list[Project] = []
    activities: list[Activity] = []
    color: str | None = None


class TeamFilter(KimaiModel):
    """Filters for team queries."""
    # Teams don't have many filter options


# Tag models

class TagEntity(KimaiModel):
    """Tag entity model."""
    id: int | None = None
    name: str
    visible: bool = True
    color: str | None = None


class TagEditForm(KimaiModel):
    """Form for creating/editing tags."""
    name: str
    color: str | None = None
    visible: bool | None = None


class TagFilter(KimaiModel):
    """Filters for tag queries."""
    name: str | None = None


# Invoice models

class Invoice(KimaiModel):
    """Invoice model."""
    id: int | None = None
    invoice_number: str = Field(alias="invoiceNumber")
    comment: str | None = None
    customer: Customer
    user: User
    created_at: datetime = Field(alias="createdAt")
    total: float = 0.0
    tax: float = 0.0
    currency: str
    due_days: int = Field(30, alias="dueDays")
    vat: float = 0.0
    status: str = "new"
    payment_date: datetime | None = Field(None, alias="paymentDate")
    meta_fields: list[dict[str, Any]] | None = Field(None, alias="metaFields")
    overdue: bool | None = None  # Whether the invoice is overdue
    invoice_filename: str | None = Field(None, alias="invoiceFilename")


class InvoiceFilter(KimaiModel):
    """Filters for invoice queries."""
    begin: datetime | None = None
    end: datetime | None = None
    customers: list[int] | None = None
    status: list[str] | None = None  # pending, paid, canceled, new
    page: int | None = None
    size: int | None = None


# Comment models (Kimai 2.57+, projects and customers)

class Comment(KimaiModel):
    """Comment on a project or customer."""
    id: int | None = None
    message: str
    created_by: User | None = Field(None, alias="createdBy")
    created_at: datetime | None = Field(None, alias="createdAt")
    pinned: bool = False


class CommentForm(KimaiModel):
    """Form for creating a comment (markdown is supported in message)."""
    message: str
    pinned: bool | None = None


# Public Holiday models

class PublicHolidayGroup(KimaiModel):
    """Public holiday group model."""
    id: int | None = None
    name: str


class PublicHoliday(KimaiModel):
    """Public holiday model."""
    id: int | None = None
    date: datetime
    name: str
    public_holiday_group: PublicHolidayGroup | None = Field(None, alias="publicHolidayGroup")
    half_day: bool = Field(False, alias="halfDay")


class PublicHolidayFilter(KimaiModel):
    """Filters for public holiday queries."""
    group: int | None = None
    begin: datetime | None = None
    end: datetime | None = None


# User extended models

class UserEntity(KimaiModel):
    """Extended user entity model (serializer group ``User_Entity``)."""
    id: int
    username: str
    alias: str | None = None
    title: str | None = None
    avatar: str | None = None
    enabled: bool = False
    roles: list[str] = []
    supervisor: User | None = None
    color: str | None = None
    locale: str | None = None
    timezone: str | None = None
    language: str | None = None
    teams: list[Team] = []
    preferences: list[dict[str, Any]] | None = None
    email: str | None = None
    account_number: str | None = Field(None, alias="accountNumber")
    system_account: bool | None = Field(None, alias="systemAccount")
    initials: str | None = None
    memberships: list[dict[str, Any]] | None = None


class UserPreference(KimaiModel):
    """Model for user preference name-value pair.

    Used for work contract settings like:
    - work_contract_type: "week" or "day"
    - hours_per_week: Total weekly hours in seconds (e.g., 144000 = 40h)
    - work_monday..work_sunday: Daily hours in seconds (e.g., 28800 = 8h)
    - holidays: Vacation days per year
    - public_holiday_group: Holiday group ID
    - work_start_day/work_last_day: Contract period (YYYY-MM-DD)
    """
    name: str = Field(..., min_length=2, max_length=50)
    value: str | None = Field(None, max_length=250)


class UserEditForm(KimaiModel):
    """Form for updating users."""
    alias: str | None = None
    title: str | None = None
    account_number: str | None = Field(None, alias="accountNumber")
    avatar: str | None = None
    color: str | None = None
    email: str
    language: str
    locale: str
    timezone: str
    supervisor: int | None = None
    roles: list[str] | None = None
    enabled: bool | None = None
    system_account: bool | None = Field(None, alias="systemAccount")
    requires_password_reset: bool | None = Field(None, alias="requiresPasswordReset")


class UserCreateForm(KimaiModel):
    """Form for creating users."""
    username: str
    alias: str | None = None
    title: str | None = None
    account_number: str | None = Field(None, alias="accountNumber")
    avatar: str | None = None
    color: str | None = None
    email: str
    language: str
    locale: str
    timezone: str
    supervisor: int | None = None
    roles: list[str] | None = None
    plain_password: str = Field(alias="plainPassword")
    plain_api_token: str | None = Field(None, alias="plainApiToken")
    enabled: bool | None = None
    system_account: bool | None = Field(None, alias="systemAccount")
    requires_password_reset: bool | None = Field(None, alias="requiresPasswordReset")


class UserFilter(KimaiModel):
    """Filters for user queries."""
    visible: int | None = 1
    order_by: str | None = Field(None, alias="orderBy")
    order: str | None = None
    term: str | None = None
    full: str | None = None


# Plugin models

class Plugin(KimaiModel):
    """Plugin model."""
    name: str
    version: str


# Configuration models

class TimesheetConfig(KimaiModel):
    """Timesheet configuration from the Kimai instance."""
    tracking_mode: str = Field("default", alias="trackingMode")
    default_begin_time: str = Field("now", alias="defaultBeginTime")
    active_entries_hard_limit: int = Field(1, alias="activeEntriesHardLimit")
    is_allow_future_times: bool = Field(True, alias="isAllowFutureTimes")
    is_allow_overlapping: bool = Field(True, alias="isAllowOverlapping")


# Calendar event model

class CalendarEvent(KimaiModel):
    """Calendar event model."""
    title: str
    color: str | None = None
    text_color: str | None = Field(None, alias="textColor")
    all_day: bool = Field(False, alias="allDay")
    start: datetime
    end: datetime | None = None


# Rate management models

class Rate(KimaiModel):
    """Rate model."""
    id: int | None = None
    user: User | None = None
    rate: float
    internal_rate: float | None = Field(None, alias="internalRate")
    is_fixed: bool = Field(False, alias="isFixed")


class RateForm(KimaiModel):
    """Form for creating/editing rates."""
    user: int | None = None
    rate: float
    internal_rate: float | None = Field(None, alias="internalRate")
    is_fixed: bool | None = Field(None, alias="isFixed")


# Meta field models

class MetaFieldForm(KimaiModel):
    """Form for updating meta fields."""
    name: str
    value: str


# Extended entity models with meta fields

# Kimai puts metaFields in the `Default` serializer group, so *every* response
# carries them and the base models above parse them. These subclasses are kept
# as the return types of the create/update client methods, where the response is
# the full entity, but they no longer add fields of their own.
#
# Ext*ended* is not Ext*panded*: `ProjectExpanded` / `ActivityExpanded` above are
# a different thing entirely. Those carry Kimai's `Expanded` serializer group, in
# which the relation is a nested object rather than an id, and they are named
# after Kimai's own schema aliases. The `*Extended` models here say nothing about
# the relations; they only mark "this response is the full entity".

class CustomerExtended(Customer):
    """Customer as returned by get/create/update (full entity)."""


class ProjectExtended(Project):
    """Project as returned by get/create/update (full entity)."""


class ActivityExtended(Activity):
    """Activity as returned by get/create/update (full entity)."""


# CRUD forms for administrative operations

class CustomerEditForm(KimaiModel):
    """Form for creating/editing customers."""
    name: str | None = None  # Required for creation
    country: str | None = None  # Required for creation (2-letter ISO code)
    currency: str | None = None  # Required for creation (3-letter ISO code)
    timezone: str | None = None  # Required for creation (e.g., "Europe/Berlin")
    number: str | None = None
    comment: str | None = None
    visible: bool | None = None
    billable: bool | None = None
    budget: float | None = None
    time_budget: TimeBudget = Field(None, alias="timeBudget")  # see _normalize_duration
    budget_type: Literal["month"] | None = Field(None, alias="budgetType")
    color: str | None = None
    phone: str | None = None
    fax: str | None = None
    mobile: str | None = None
    email: str | None = None
    homepage: str | None = None
    # Structured address fields (preferred over 'address')
    address_line1: str | None = Field(None, alias="addressLine1")
    address_line2: str | None = Field(None, alias="addressLine2")
    address_line3: str | None = Field(None, alias="addressLine3")
    post_code: str | None = Field(None, alias="postCode")
    city: str | None = None
    address: str | None = None  # Unstructured address (legacy)
    contact: str | None = None
    company: str | None = None
    vat_id: str | None = Field(None, alias="vatId")
    buyer_reference: str | None = Field(None, alias="buyerReference")
    invoice_text: str | None = Field(None, alias="invoiceText")
    invoice_template: str | None = Field(None, alias="invoiceTemplate")
    # Kimai 2.63+ (kimai/kimai#5857, #5855)
    language: str | None = None  # e.g. "de", "en"
    invoice_email: str | None = Field(None, alias="invoiceEmail")
    teams: list[int] | None = None  # Team IDs; Kimai binds this on create only
    meta_fields: list[dict[str, Any]] | None = Field(None, alias="metaFields")


class ProjectEditForm(KimaiModel):
    """Form for creating/editing projects."""
    name: str | None = None  # Required for creation
    customer: int | None = None  # Required for creation (Customer ID)
    comment: str | None = None
    visible: bool | None = None
    billable: bool | None = None
    budget: float | None = None
    time_budget: TimeBudget = Field(None, alias="timeBudget")  # see _normalize_duration
    budget_type: Literal["month"] | None = Field(None, alias="budgetType")
    color: str | None = None
    global_activities: bool | None = Field(None, alias="globalActivities")
    number: str | None = None
    order_number: str | None = Field(None, alias="orderNumber")
    order_date: str | None = Field(None, alias="orderDate")  # Format: YYYY-MM-DD
    # Kimai accepts YYYY-MM-DD when creating, but the PATCH form rejects a
    # date-only value ("Please enter a valid date."); updates need the full
    # YYYY-MM-DDTHH:MM:SS form. Passed through verbatim - do not call
    # .isoformat() on these, they are strings.
    start: str | None = None
    end: str | None = None
    invoice_text: str | None = Field(None, alias="invoiceText")
    teams: list[int] | None = None  # Team IDs; Kimai binds this on create only
    meta_fields: list[dict[str, Any]] | None = Field(None, alias="metaFields")


class ActivityEditForm(KimaiModel):
    """Form for creating/editing activities."""
    name: str  # Required
    project: int | None = None  # Project ID (None = global activity)
    comment: str | None = None
    visible: bool | None = None
    billable: bool | None = None
    budget: float | None = None
    time_budget: TimeBudget = Field(None, alias="timeBudget")  # see _normalize_duration
    budget_type: Literal["month"] | None = Field(None, alias="budgetType")
    color: str | None = None
    number: str | None = None
    invoice_text: str | None = Field(None, alias="invoiceText")
    teams: list[int] | None = None  # Team IDs; Kimai binds this on create only
    meta_fields: list[dict[str, Any]] | None = Field(None, alias="metaFields")
