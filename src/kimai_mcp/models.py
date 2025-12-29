"""Data models for Kimai API entities."""

from datetime import datetime
from typing import List, Optional, Dict, Any, Literal

from pydantic import BaseModel, Field


class User(BaseModel):
    """User model."""
    id: int
    username: str
    alias: Optional[str] = None
    title: Optional[str] = None
    enabled: bool = False
    color: Optional[str] = None


class Customer(BaseModel):
    """Customer model."""
    id: int
    name: str
    country: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    number: Optional[str] = None
    comment: Optional[str] = None
    visible: bool = True
    billable: bool = True
    color: Optional[str] = None

    phone: Optional[str] = None
    fax: Optional[str] = None
    mobile: Optional[str] = None
    homepage: Optional[str] = None
    company: Optional[str] = None


class Project(BaseModel):
    """Project model."""
    id: int
    name: str
    customer: Optional[int] = None
    comment: Optional[str] = None
    visible: bool = True
    billable: bool = True
    global_activities: bool = Field(True, alias="globalActivities")
    number: Optional[str] = None
    color: Optional[str] = None


class Activity(BaseModel):
    """Activity model."""
    id: int
    name: str
    project: Optional[int] = None
    comment: Optional[str] = None
    visible: bool = True
    billable: bool = True
    number: Optional[str] = None
    color: Optional[str] = None


class TimesheetEntity(BaseModel):
    """Timesheet entity model."""
    id: Optional[int] = None
    activity: int
    project: int
    user: Optional[int] = None
    tags: List[str] = []
    begin: datetime
    end: Optional[datetime] = None
    duration: Optional[int] = 0
    description: Optional[str] = None
    rate: Optional[float] = 0.0
    internal_rate: Optional[float] = Field(None, alias="internalRate")
    fixed_rate: Optional[float] = Field(None, alias="fixedRate")
    hourly_rate: Optional[float] = Field(None, alias="hourlyRate")
    exported: bool = False
    billable: bool = True
    meta_fields: Optional[List[Dict[str, Any]]] = Field(None, alias="metaFields")
    break_duration: Optional[int] = Field(None, alias="break")


class TimesheetEditForm(BaseModel):
    """Timesheet edit form for creating/updating timesheets."""
    begin: Optional[datetime] = None
    end: Optional[datetime] = None
    project: Optional[int] = None # Required for creation
    activity: Optional[int] = None  # Required for creation
    description: Optional[str] = None
    fixed_rate: Optional[float] = Field(None, alias="fixedRate")
    hourly_rate: Optional[float] = Field(None, alias="hourlyRate")
    user: Optional[int] = None
    tags: Optional[str] = None
    exported: Optional[bool] = None
    billable: Optional[bool] = None
    break_duration: Optional[int] = Field(None, alias="break")


class TimesheetFilter(BaseModel):
    """Filters for timesheet queries."""
    user: Optional[str] = None  # User ID or "all"
    users: Optional[List[int]] = None
    customer: Optional[int] = None
    customers: Optional[List[int]] = None
    project: Optional[int] = None
    projects: Optional[List[int]] = None
    activity: Optional[int] = None
    activities: Optional[List[int]] = None
    page: Optional[int] = None
    size: Optional[int] = None
    tags: Optional[List[str]] = None
    order_by: Optional[str] = Field(None, alias="orderBy")  # id, begin, end, rate
    order: Optional[str] = None  # ASC, DESC
    begin: Optional[str | datetime] = None  # HTML5 date format (YYYY-MM-DD)
    end: Optional[str | datetime] = None  # HTML5 date format (YYYY-MM-DD)
    exported: Optional[int] = None  # 0=not exported, 1=exported
    active: Optional[int] = None  # 0=stopped, 1=active
    billable: Optional[int] = None  # 0=non-billable, 1=billable
    full: Optional[str] = None  # 0|1|false|true
    term: Optional[str] = None
    modified_after: Optional[str | datetime] = Field(None, alias="modified_after")  # HTML5 date format


class ProjectFilter(BaseModel):
    """Filters for project queries."""
    customer: Optional[int] = None
    customers: Optional[List[int]] = None
    visible: Optional[int] = 1  # 1=visible, 2=hidden, 3=both
    start: Optional[str] = None  # HTML5 date format (YYYY-MM-DD)
    end: Optional[str] = None  # HTML5 date format (YYYY-MM-DD)
    ignore_dates: Optional[str] = Field(None, alias="ignoreDates")
    global_activities: Optional[str] = Field(None, alias="globalActivities")  # 0|1
    order: Optional[str] = None  # ASC, DESC
    order_by: Optional[str] = Field(None, alias="orderBy")  # id, name, customer
    term: Optional[str] = None


class ActivityFilter(BaseModel):
    """Filters for activity queries."""
    project: Optional[int] = None
    projects: Optional[List[int]] = None
    visible: Optional[int] = 1  # 1=visible, 2=hidden, 3=all
    globals: Optional[str] = None  # 0|1
    order_by: Optional[str] = Field(None, alias="orderBy")  # id, name, project
    order: Optional[str] = None  # ASC, DESC
    term: Optional[str] = None


class CustomerFilter(BaseModel):
    """Filters for customer queries."""
    visible: Optional[int] = 1  # 1=visible, 2=hidden, 3=both
    order: Optional[str] = None  # ASC, DESC
    order_by: Optional[str] = Field(None, alias="orderBy")  # id, name
    term: Optional[str] = None


class ApiError(BaseModel):
    """API error response."""
    message: str
    code: Optional[int] = None


class Version(BaseModel):
    """Kimai version information."""
    version: str
    version_id: int = Field(alias="versionId")
    copyright: str


# Absence models

class AbsenceForm(BaseModel):
    """Form for creating absences."""
    half_day: Optional[bool] = Field(None, alias="halfDay")
    duration: Optional[str] = None  # Duration string format (e.g., "01:30")
    comment: str
    user: Optional[int] = None  # User ID (requires permission, defaults to current user)
    date: str  # Date format YYYY-MM-DD
    end: Optional[str] = None  # End date for multi-day absences
    type: Literal[
        "holiday", "time_off", "sickness", "sickness_child", "other", "parental", "unpaid_vacation"] = "other"


class Absence(BaseModel):
    """Absence model matching API Absence2 schema."""
    id: Optional[int] = None
    user: User
    date: datetime
    duration: Optional[int] = None  # Duration in seconds according to API
    type: str = "other"
    status: str = "new"
    half_day: bool = Field(False, alias="halfDay")
    # Optional fields that might be present in responses
    comment: Optional[str] = None
    end_date: Optional[datetime] = Field(None, alias="endDate")


class AbsenceFilter(BaseModel):
    """Filters for absence queries."""
    user: Optional[str] = None
    begin: Optional[str] = None  # HTML5 date format (YYYY-MM-DD)
    end: Optional[str] = None  # HTML5 date format (YYYY-MM-DD)
    status: Optional[str] = None  # approved, open, all


# Team models

class TeamMember(BaseModel):
    """Team member model."""
    user: User
    teamlead: bool = False


class TeamEditForm(BaseModel):
    """Form for creating/editing teams."""
    name: str
    color: Optional[str] = None
    members: List[Dict[str, Any]]  # List of {user: int, teamlead: bool}


class Team(BaseModel):
    """Team model."""
    id: Optional[int] = None
    name: str
    members: List[TeamMember] = []
    customers: List[Customer] = []
    projects: List[Project] = []
    activities: List[Activity] = []
    color: Optional[str] = None


class TeamFilter(BaseModel):
    """Filters for team queries."""
    pass  # Teams don't have many filter options


# Tag models

class TagEntity(BaseModel):
    """Tag entity model."""
    id: Optional[int] = None
    name: str
    visible: bool = True
    color: Optional[str] = None


class TagEditForm(BaseModel):
    """Form for creating/editing tags."""
    name: str
    color: Optional[str] = None
    visible: Optional[bool] = None


class TagFilter(BaseModel):
    """Filters for tag queries."""
    name: Optional[str] = None


# Invoice models

class Invoice(BaseModel):
    """Invoice model."""
    id: Optional[int] = None
    invoice_number: str = Field(alias="invoiceNumber")
    comment: Optional[str] = None
    customer: Customer
    user: User
    created_at: datetime = Field(alias="createdAt")
    total: float = 0.0
    tax: float = 0.0
    currency: str
    due_days: int = Field(30, alias="dueDays")
    vat: float = 0.0
    status: str = "new"
    payment_date: Optional[datetime] = Field(None, alias="paymentDate")
    meta_fields: Optional[List[Dict[str, Any]]] = Field(None, alias="metaFields")
    overdue: Optional[bool] = None  # Whether the invoice is overdue


class InvoiceFilter(BaseModel):
    """Filters for invoice queries."""
    begin: Optional[datetime] = None
    end: Optional[datetime] = None
    customers: Optional[List[int]] = None
    status: Optional[List[str]] = None  # pending, paid, canceled, new
    page: Optional[int] = None
    size: Optional[int] = None


# Public Holiday models

class PublicHolidayGroup(BaseModel):
    """Public holiday group model."""
    id: Optional[int] = None
    name: str


class PublicHoliday(BaseModel):
    """Public holiday model."""
    id: Optional[int] = None
    date: datetime
    name: str
    public_holiday_group: Optional[PublicHolidayGroup] = Field(None, alias="publicHolidayGroup")
    half_day: bool = Field(False, alias="halfDay")


class PublicHolidayFilter(BaseModel):
    """Filters for public holiday queries."""
    group: Optional[int] = None
    begin: Optional[datetime] = None
    end: Optional[datetime] = None


# User extended models

class UserEntity(BaseModel):
    """Extended user entity model."""
    id: int
    username: str
    alias: Optional[str] = None
    title: Optional[str] = None
    avatar: Optional[str] = None
    enabled: bool = False
    roles: List[str] = []
    supervisor: Optional[User] = None
    color: Optional[str] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    teams: List[Team] = []
    preferences: Optional[List[Dict[str, Any]]] = None


class UserEditForm(BaseModel):
    """Form for updating users."""
    alias: Optional[str] = None
    title: Optional[str] = None
    account_number: Optional[str] = Field(None, alias="accountNumber")
    avatar: Optional[str] = None
    color: Optional[str] = None
    email: str
    language: str
    locale: str
    timezone: str
    supervisor: Optional[int] = None
    roles: Optional[List[str]] = None
    enabled: Optional[bool] = None
    system_account: Optional[bool] = Field(None, alias="systemAccount")
    requires_password_reset: Optional[bool] = Field(None, alias="requiresPasswordReset")


class UserCreateForm(BaseModel):
    """Form for creating users."""
    username: str
    alias: Optional[str] = None
    title: Optional[str] = None
    account_number: Optional[str] = Field(None, alias="accountNumber")
    avatar: Optional[str] = None
    color: Optional[str] = None
    email: str
    language: str
    locale: str
    timezone: str
    supervisor: Optional[int] = None
    roles: Optional[List[str]] = None
    plain_password: str = Field(alias="plainPassword")
    plain_api_token: Optional[str] = Field(None, alias="plainApiToken")
    enabled: Optional[bool] = None
    system_account: Optional[bool] = Field(None, alias="systemAccount")
    requires_password_reset: Optional[bool] = Field(None, alias="requiresPasswordReset")


class UserFilter(BaseModel):
    """Filters for user queries."""
    visible: Optional[int] = 1
    order_by: Optional[str] = Field(None, alias="orderBy")
    order: Optional[str] = None
    term: Optional[str] = None
    full: Optional[str] = None


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
    color: Optional[str] = None
    text_color: Optional[str] = Field(None, alias="textColor")
    all_day: bool = Field(False, alias="allDay")
    start: datetime
    end: Optional[datetime] = None


# Rate management models

class Rate(BaseModel):
    """Rate model."""
    id: Optional[int] = None
    user: Optional[User] = None
    rate: float
    internal_rate: Optional[float] = Field(None, alias="internalRate")
    is_fixed: bool = Field(False, alias="isFixed")


class RateForm(BaseModel):
    """Form for creating/editing rates."""
    user: Optional[int] = None
    rate: float
    internal_rate: Optional[float] = Field(None, alias="internalRate")
    is_fixed: Optional[bool] = Field(None, alias="isFixed")


# Meta field models

class MetaField(BaseModel):
    """Meta field model."""
    name: str
    value: Optional[str] = None


class MetaFieldForm(BaseModel):
    """Form for updating meta fields."""
    name: str
    value: str


# Extended entity models with meta fields

class CustomerExtended(Customer):
    """Extended customer model with meta fields."""
    meta_fields: Optional[List[MetaField]] = Field(None, alias="metaFields")


class ProjectExtended(Project):
    """Extended project model with meta fields."""
    meta_fields: Optional[List[MetaField]] = Field(None, alias="metaFields")


class ActivityExtended(Activity):
    """Extended activity model with meta fields."""
    meta_fields: Optional[List[MetaField]] = Field(None, alias="metaFields")


# CRUD forms for administrative operations

class CustomerEditForm(BaseModel):
    """Form for creating/editing customers."""
    name: Optional[str] = None  # Required for creation
    country: Optional[str] = None  # Required for creation (2-letter ISO code)
    currency: Optional[str] = None  # Required for creation (3-letter ISO code)
    timezone: Optional[str] = None  # Required for creation (e.g., "Europe/Berlin")
    number: Optional[str] = None
    comment: Optional[str] = None
    visible: Optional[bool] = None
    billable: Optional[bool] = None
    budget: Optional[float] = None
    time_budget: Optional[str] = Field(None, alias="timeBudget")  # Duration format
    budget_type: Optional[Literal["month"]] = Field(None, alias="budgetType")
    color: Optional[str] = None
    phone: Optional[str] = None
    fax: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    homepage: Optional[str] = None
    # Structured address fields (preferred over 'address')
    address_line1: Optional[str] = Field(None, alias="addressLine1")
    address_line2: Optional[str] = Field(None, alias="addressLine2")
    address_line3: Optional[str] = Field(None, alias="addressLine3")
    post_code: Optional[str] = Field(None, alias="postCode")
    city: Optional[str] = None
    address: Optional[str] = None  # Unstructured address (legacy)
    contact: Optional[str] = None
    company: Optional[str] = None
    vat_id: Optional[str] = Field(None, alias="vatId")
    buyer_reference: Optional[str] = Field(None, alias="buyerReference")
    invoice_text: Optional[str] = Field(None, alias="invoiceText")
    invoice_template: Optional[str] = Field(None, alias="invoiceTemplate")
    teams: Optional[int] = None  # Team ID
    meta_fields: Optional[List[Dict[str, Any]]] = Field(None, alias="metaFields")


class ProjectEditForm(BaseModel):
    """Form for creating/editing projects."""
    name: Optional[str] = None  # Required for creation
    customer: Optional[int] = None  # Required for creation (Customer ID)
    comment: Optional[str] = None
    visible: Optional[bool] = None
    billable: Optional[bool] = None
    budget: Optional[float] = None
    time_budget: Optional[str] = Field(None, alias="timeBudget")  # Duration format
    budget_type: Optional[Literal["month"]] = Field(None, alias="budgetType")
    color: Optional[str] = None
    global_activities: Optional[bool] = Field(None, alias="globalActivities")
    number: Optional[str] = None
    order_number: Optional[str] = Field(None, alias="orderNumber")
    order_date: Optional[str] = Field(None, alias="orderDate")  # Format: YYYY-MM-DD
    start: Optional[str] = None  # Format: YYYY-MM-DD
    end: Optional[str] = None  # Format: YYYY-MM-DD
    invoice_text: Optional[str] = Field(None, alias="invoiceText")
    teams: Optional[int] = None  # Team ID
    meta_fields: Optional[List[Dict[str, Any]]] = Field(None, alias="metaFields")


class ActivityEditForm(BaseModel):
    """Form for creating/editing activities."""
    name: str  # Required
    project: Optional[int] = None  # Project ID (None = global activity)
    comment: Optional[str] = None
    visible: Optional[bool] = None
    billable: Optional[bool] = None
    budget: Optional[float] = None
    time_budget: Optional[str] = Field(None, alias="timeBudget")  # Duration format
    budget_type: Optional[Literal["month"]] = Field(None, alias="budgetType")
    color: Optional[str] = None
    number: Optional[str] = None
    invoice_text: Optional[str] = Field(None, alias="invoiceText")
    teams: Optional[int] = None  # Team ID
    meta_fields: Optional[List[Dict[str, Any]]] = Field(None, alias="metaFields")
