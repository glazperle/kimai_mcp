"""Data models for Kimai API entities."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class User(BaseModel):
    """User model."""
    id: int
    username: str
    alias: str | None = None
    title: str | None = None
    enabled: bool = False
    color: str | None = None


class Customer(BaseModel):
    """Customer model."""
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

    # Kimai 2.63+ (kimai/kimai#5857, #5855). Only returned by the collection
    # endpoint when it is called with full=1.
    language: str | None = None
    invoice_email: str | None = Field(None, alias="invoiceEmail")


class Project(BaseModel):
    """Project model."""
    id: int
    name: str
    customer: int | None = None
    comment: str | None = None
    visible: bool = True
    billable: bool = True
    global_activities: bool = Field(True, alias="globalActivities")
    number: str | None = None
    color: str | None = None


class Activity(BaseModel):
    """Activity model."""
    id: int
    name: str
    project: int | None = None
    comment: str | None = None
    visible: bool = True
    billable: bool = True
    number: str | None = None
    color: str | None = None


class TimesheetEntity(BaseModel):
    """Timesheet entity model."""
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


class TimesheetEditForm(BaseModel):
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
    break_duration: int | None = Field(None, alias="break")


class TimesheetFilter(BaseModel):
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


class ProjectFilter(BaseModel):
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


class ActivityFilter(BaseModel):
    """Filters for activity queries."""
    project: int | None = None
    projects: list[int] | None = None
    visible: int | None = 1  # 1=visible, 2=hidden, 3=all
    globals: str | None = None  # 0|1
    order_by: str | None = Field(None, alias="orderBy")  # id, name, project
    order: str | None = None  # ASC, DESC
    term: str | None = None


class CustomerFilter(BaseModel):
    """Filters for customer queries."""
    visible: int | None = 1  # 1=visible, 2=hidden, 3=both
    order: str | None = None  # ASC, DESC
    order_by: str | None = Field(None, alias="orderBy")  # id, name
    term: str | None = None
    # Kimai 2.62+: 1 returns the full detail set (needs the 'details_customer'
    # permission; Kimai silently falls back to the short form without it).
    full: int | None = None


class ApiError(BaseModel):
    """API error response."""
    message: str
    code: int | None = None


class Version(BaseModel):
    """Kimai version information."""
    version: str
    version_id: int = Field(alias="versionId")
    copyright: str


# Absence models

class AbsenceForm(BaseModel):
    """Form for creating absences."""
    half_day: bool | None = Field(None, alias="halfDay")
    duration: str | None = None  # Duration string format (e.g., "01:30")
    comment: str
    user: int | None = None  # User ID (requires permission, defaults to current user)
    date: str  # Date format YYYY-MM-DD
    end: str | None = None  # End date for multi-day absences
    type: Literal[
        "holiday", "time_off", "sickness", "sickness_child", "other", "parental", "unpaid_vacation"] = "other"


class Absence(BaseModel):
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


class AbsenceFilter(BaseModel):
    """Filters for absence queries."""
    user: str | None = None
    begin: str | None = None  # HTML5 date format (YYYY-MM-DD)
    end: str | None = None  # HTML5 date format (YYYY-MM-DD)
    status: str | None = None  # approved, open, all


# Team models

class TeamMember(BaseModel):
    """Team member model."""
    user: User
    teamlead: bool = False


class TeamEditForm(BaseModel):
    """Form for creating/editing teams."""
    name: str
    color: str | None = None
    members: list[dict[str, Any]]  # List of {user: int, teamlead: bool}


class Team(BaseModel):
    """Team model."""
    id: int | None = None
    name: str
    members: list[TeamMember] = []
    customers: list[Customer] = []
    projects: list[Project] = []
    activities: list[Activity] = []
    color: str | None = None


class TeamFilter(BaseModel):
    """Filters for team queries."""
    # Teams don't have many filter options


# Tag models

class TagEntity(BaseModel):
    """Tag entity model."""
    id: int | None = None
    name: str
    visible: bool = True
    color: str | None = None


class TagEditForm(BaseModel):
    """Form for creating/editing tags."""
    name: str
    color: str | None = None
    visible: bool | None = None


class TagFilter(BaseModel):
    """Filters for tag queries."""
    name: str | None = None


# Invoice models

class Invoice(BaseModel):
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


class InvoiceFilter(BaseModel):
    """Filters for invoice queries."""
    begin: datetime | None = None
    end: datetime | None = None
    customers: list[int] | None = None
    status: list[str] | None = None  # pending, paid, canceled, new
    page: int | None = None
    size: int | None = None


# Comment models (Kimai 2.57+, projects and customers)

class Comment(BaseModel):
    """Comment on a project or customer."""
    id: int | None = None
    message: str
    created_by: User | None = Field(None, alias="createdBy")
    created_at: datetime | None = Field(None, alias="createdAt")
    pinned: bool = False


class CommentForm(BaseModel):
    """Form for creating a comment (markdown is supported in message)."""
    message: str
    pinned: bool | None = None


# Public Holiday models

class PublicHolidayGroup(BaseModel):
    """Public holiday group model."""
    id: int | None = None
    name: str


class PublicHoliday(BaseModel):
    """Public holiday model."""
    id: int | None = None
    date: datetime
    name: str
    public_holiday_group: PublicHolidayGroup | None = Field(None, alias="publicHolidayGroup")
    half_day: bool = Field(False, alias="halfDay")


class PublicHolidayFilter(BaseModel):
    """Filters for public holiday queries."""
    group: int | None = None
    begin: datetime | None = None
    end: datetime | None = None


# User extended models

class UserEntity(BaseModel):
    """Extended user entity model."""
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


class UserPreference(BaseModel):
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


class UserEditForm(BaseModel):
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


class UserCreateForm(BaseModel):
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


class UserFilter(BaseModel):
    """Filters for user queries."""
    visible: int | None = 1
    order_by: str | None = Field(None, alias="orderBy")
    order: str | None = None
    term: str | None = None
    full: str | None = None


# Plugin models

class Plugin(BaseModel):
    """Plugin model."""
    name: str
    version: str


# Configuration models

class TimesheetConfig(BaseModel):
    """Timesheet configuration from the Kimai instance."""
    tracking_mode: str = Field("default", alias="trackingMode")
    default_begin_time: str = Field("now", alias="defaultBeginTime")
    active_entries_hard_limit: int = Field(1, alias="activeEntriesHardLimit")
    is_allow_future_times: bool = Field(True, alias="isAllowFutureTimes")
    is_allow_overlapping: bool = Field(True, alias="isAllowOverlapping")


# Calendar event model

class CalendarEvent(BaseModel):
    """Calendar event model."""
    title: str
    color: str | None = None
    text_color: str | None = Field(None, alias="textColor")
    all_day: bool = Field(False, alias="allDay")
    start: datetime
    end: datetime | None = None


# Rate management models

class Rate(BaseModel):
    """Rate model."""
    id: int | None = None
    user: User | None = None
    rate: float
    internal_rate: float | None = Field(None, alias="internalRate")
    is_fixed: bool = Field(False, alias="isFixed")


class RateForm(BaseModel):
    """Form for creating/editing rates."""
    user: int | None = None
    rate: float
    internal_rate: float | None = Field(None, alias="internalRate")
    is_fixed: bool | None = Field(None, alias="isFixed")


# Meta field models

class MetaField(BaseModel):
    """Meta field model."""
    name: str
    value: str | None = None


class MetaFieldForm(BaseModel):
    """Form for updating meta fields."""
    name: str
    value: str


# Extended entity models with meta fields

class CustomerExtended(Customer):
    """Extended customer model with meta fields."""
    meta_fields: list[MetaField] | None = Field(None, alias="metaFields")


class ProjectExtended(Project):
    """Extended project model with meta fields."""
    meta_fields: list[MetaField] | None = Field(None, alias="metaFields")


class ActivityExtended(Activity):
    """Extended activity model with meta fields."""
    meta_fields: list[MetaField] | None = Field(None, alias="metaFields")


# CRUD forms for administrative operations

class CustomerEditForm(BaseModel):
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
    time_budget: str | None = Field(None, alias="timeBudget")  # Duration format
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
    teams: int | None = None  # Team ID
    meta_fields: list[dict[str, Any]] | None = Field(None, alias="metaFields")


class ProjectEditForm(BaseModel):
    """Form for creating/editing projects."""
    name: str | None = None  # Required for creation
    customer: int | None = None  # Required for creation (Customer ID)
    comment: str | None = None
    visible: bool | None = None
    billable: bool | None = None
    budget: float | None = None
    time_budget: str | None = Field(None, alias="timeBudget")  # Duration format
    budget_type: Literal["month"] | None = Field(None, alias="budgetType")
    color: str | None = None
    global_activities: bool | None = Field(None, alias="globalActivities")
    number: str | None = None
    order_number: str | None = Field(None, alias="orderNumber")
    order_date: str | None = Field(None, alias="orderDate")  # Format: YYYY-MM-DD
    start: str | None = None  # Format: YYYY-MM-DD
    end: str | None = None  # Format: YYYY-MM-DD
    invoice_text: str | None = Field(None, alias="invoiceText")
    teams: int | None = None  # Team ID
    meta_fields: list[dict[str, Any]] | None = Field(None, alias="metaFields")


class ActivityEditForm(BaseModel):
    """Form for creating/editing activities."""
    name: str  # Required
    project: int | None = None  # Project ID (None = global activity)
    comment: str | None = None
    visible: bool | None = None
    billable: bool | None = None
    budget: float | None = None
    time_budget: str | None = Field(None, alias="timeBudget")  # Duration format
    budget_type: Literal["month"] | None = Field(None, alias="budgetType")
    color: str | None = None
    number: str | None = None
    invoice_text: str | None = Field(None, alias="invoiceText")
    teams: int | None = None  # Team ID
    meta_fields: list[dict[str, Any]] | None = Field(None, alias="metaFields")
