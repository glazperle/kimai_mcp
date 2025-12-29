"""Kimai API client wrapper."""

from typing import Dict, List, Optional, Any, Union, Tuple
import logging
from datetime import datetime
import httpx

from .models import (
    TimesheetEntity, TimesheetEditForm, TimesheetFilter,
    Project, ProjectFilter, ProjectEditForm, ProjectExtended,
    Activity, ActivityFilter, ActivityEditForm, ActivityExtended,
    Customer, CustomerFilter, CustomerEditForm, CustomerExtended,
    User, UserEntity, UserFilter, UserEditForm, UserCreateForm,
    Version, Absence, AbsenceForm, AbsenceFilter,
    Team, TeamEditForm, TagEntity, TagEditForm, TagFilter,
    Invoice, InvoiceFilter,
    PublicHoliday, PublicHolidayFilter,
    Plugin, CalendarEvent, TimesheetConfig,
    Rate, RateForm, MetaFieldForm
)

logger = logging.getLogger(__name__)


class KimaiAPIError(Exception):
    """Kimai API error."""

    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Any] = None):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(self.message)


class KimaiClient:
    """Kimai API client."""

    def __init__(self, base_url: str, api_token: str, timeout: float = 30.0,
                 ssl_verify: Union[bool, str] = True):
        """Initialize Kimai client.

        Args:
            base_url: Base URL of Kimai instance (e.g., https://kimai.example.com)
            api_token: API authentication token
            timeout: Request timeout in seconds
            ssl_verify: SSL verification setting:
                - True: Use default CA bundle (default)
                - False: Disable SSL verification (not recommended)
                - str: Path to CA certificate file or directory
        """
        self.base_url = base_url.rstrip('/')
        self.api_token = api_token
        self.timeout = timeout
        self.ssl_verify = ssl_verify
        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/api",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            timeout=timeout,
            verify=ssl_verify
        )
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
    
    async def _request(self, method: str, endpoint: str, **kwargs) -> Union[Dict, List]:
        """Make an API request.
        
        Args:
            method: HTTP method
            endpoint: API endpoint (without /api prefix)
            **kwargs: Additional request parameters
            
        Returns:
            Parsed JSON response
            
        Raises:
            KimaiAPIError: On API errors
        """
        try:
            response = await self._client.request(method, endpoint, **kwargs)
            response.raise_for_status()

            if response.status_code == 204:
                return {}

            return response.json()
            
        except httpx.HTTPStatusError as e:
            # Try to parse error response
            error_details: Optional[Any] = None
            try:
                error_data = e.response.json()
                message = error_data.get('message', str(e))

                # Helper to prune empty dicts recursively
                def _prune_empty_dicts(obj: Any) -> Any:
                    if isinstance(obj, dict):
                        # First prune children
                        pruned = {k: _prune_empty_dicts(v) for k, v in obj.items()}
                        # Then drop keys where value is an empty dict
                        return {k: v for k, v in pruned.items() if not (isinstance(v, dict) and len(v) == 0)}
                    elif isinstance(obj, list):
                        return [_prune_empty_dicts(v) for v in obj]
                    else:
                        return obj

                # Extract errors if present and prune empty dicts
                if isinstance(error_data, dict):
                    if 'errors' in error_data:
                        error_details = _prune_empty_dicts(error_data['errors'])
                    else:
                        # Fallback to full payload (pruned) for context
                        error_details = _prune_empty_dicts(error_data)
                else:
                    error_details = None
            except Exception:
                message = str(e)
                error_details = None

            logging.error(
                f"API error: {message} for request {method} {endpoint}" + (f" with params {kwargs}" if kwargs else "")
                + (f" | details: {error_details}" if error_details else "")
            )

            raise KimaiAPIError(message, e.response.status_code, details=error_details)
        except httpx.RequestError as e:
            logging.error(
                f"API error: {str(e)} for request {method} {endpoint}" + (f" with params {kwargs}" if kwargs else "")
            )
            raise KimaiAPIError(f"Request failed: {str(e)}")
    
    # Version and status endpoints
    
    async def get_version(self) -> Version:
        """Get Kimai version information."""
        data = await self._request("GET", "/version")
        return Version(**data)
    
    async def ping(self) -> Dict[str, str]:
        """Ping the API to test connectivity."""
        return await self._request("GET", "/ping")

    # Configuration endpoints

    async def get_timesheet_config(self) -> TimesheetConfig:
        """Get timesheet configuration.

        Returns tracking mode, limits, and rules for timesheets.
        """
        data = await self._request("GET", "/config/timesheet")
        return TimesheetConfig(**data)

    async def get_color_config(self) -> Dict[str, str]:
        """Get configured color codes.

        Returns a mapping of color names to hex codes.
        """
        return await self._request("GET", "/config/colors")

    async def get_plugins(self) -> List[Plugin]:
        """Get list of installed plugins."""
        data = await self._request("GET", "/plugins")
        return [Plugin(**item) for item in data]

    # User endpoints
    
    async def get_current_user(self) -> User:
        """Get current authenticated user."""
        data = await self._request("GET", "/users/me")
        return User(**data)
    
    async def get_users(self, visible: int = 1, term: Optional[str] = None, full: bool = False) -> List[User]:
        """Get list of users.
        
        Args:
            visible: 1=visible, 2=hidden, 3=all
            term: Search term
            full: Whether to fetch full objects including subresources (default: False for performance)
        """
        params = {"visible": visible, "full": "true" if full else "false"}
        if term:
            params["term"] = term
        
        data = await self._request("GET", "/users", params=params)
        return [User(**item) for item in data]
    
    # Timesheet endpoints
    
    async def get_timesheets(self, filters: Optional[TimesheetFilter] = None) -> Tuple[List[TimesheetEntity], bool, Optional[int]]:
        """Get list of timesheets.
        
        Args:
            filters: Timesheet filters

        Returns:
            * List of timesheets and a flag indicating if there are more results to fetch
            * Did we fetched all timesheets?
            * The last page fetched
        """
        params = {}
        should_paginate_all = False
        
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)
            
            # Determine if we should fetch all pages (smart defaults)
            # Auto-paginate when:
            # 1. A time range is specified (begin or end)
            # 2. Filtering by specific user/project/customer
            # 3. Not manually paginating (no page specified)
            # 4. Not using a large size limit (size <= 100 or not specified)
            has_time_filter = filters.begin is not None or filters.end is not None
            has_entity_filter = (
                filters.user is not None or 
                filters.users is not None or
                filters.projects is not None or
                filters.customers is not None or
                filters.activities is not None
            )
            manual_pagination = filters.page is not None
            large_size = filters.size is not None and filters.size > 100
            
            should_paginate_all = (
                (has_time_filter or has_entity_filter) and 
                not manual_pagination and 
                not large_size
            )
            
            if filters.begin:
                if isinstance(filters.begin, datetime):
                    params['begin'] = filters.begin.replace(microsecond=0).isoformat()
                else:
                    params['begin'] = filters.begin
            if filters.end:
                if isinstance(filters.end, datetime):
                    params['end'] = filters.end.replace(microsecond=0).isoformat()
                else:
                    params['end'] = filters.end
            if filters.modified_after:
                if isinstance(filters.modified_after, datetime):
                    params['modified_after'] = filters.modified_after.replace(microsecond=0).isoformat()
                else:
                    params['modified_after'] = filters.modified_after
            
            # Handle array parameters
            if filters.users:
                params['users[]'] = filters.users
                del params['users']
            if filters.customers:
                params['customers[]'] = filters.customers
                del params['customers']
            if filters.projects:
                params['projects[]'] = filters.projects
                del params['projects']
            if filters.activities:
                params['activities[]'] = filters.activities
                del params['activities']
            if filters.tags:
                params['tags[]'] = filters.tags
                del params['tags']
        
        # If not auto-paginating, just return single page
        if not should_paginate_all:
            data = await self._request("GET", "/timesheets", params=params)
            if filters and filters.size:
                if filters.size > len(data):
                    fetched_all = True
                else:
                    fetched_all = False
            elif len(data) < 50:
                fetched_all = True
            else:
                fetched_all = False
            return [TimesheetEntity(**item) for item in data], fetched_all, filters.page if filters and filters.page else 1
        
        # Auto-pagination logic
        all_timesheets = []
        page = 1
        page_size = filters.size if filters and filters.size else 50
        fetched_all = True
        
        while True:
            # Set pagination params
            paginated_params = params.copy()
            paginated_params['page'] = page
            paginated_params['size'] = page_size
            
            # Fetch page
            data = await self._request("GET", "/timesheets", params=paginated_params)

            if not data:
                break
                
            all_timesheets.extend([TimesheetEntity(**item) for item in data])

            if len(data) < page_size:
                break
                
            page += 1
            
            if page > 100:
                fetched_all = False
                break
        
        return all_timesheets, fetched_all, page
    
    async def get_active_timesheets(self) -> List[TimesheetEntity]:
        """Get active timesheets for current user."""
        data = await self._request("GET", "/timesheets/active")
        return [TimesheetEntity(**item) for item in data]
    
    async def get_recent_timesheets(self, begin: Optional[datetime] = None, size: int = 10) -> List[TimesheetEntity]:
        """Get recent timesheet activities.
        
        Args:
            begin: Only records after this date
            size: Number of entries to return
        """
        params = {"size": size}
        if begin:
            params["begin"] = begin.isoformat()
        
        data = await self._request("GET", "/timesheets/recent", params=params)
        return [TimesheetEntity(**item) for item in data]
    
    async def get_timesheet(self, timesheet_id: int) -> TimesheetEntity:
        """Get a single timesheet by ID."""
        data = await self._request("GET", f"/timesheets/{timesheet_id}")
        return TimesheetEntity(**data)
    
    async def create_timesheet(self, timesheet: TimesheetEditForm) -> TimesheetEntity:
        """Create a new timesheet.

        Args:
            timesheet: Timesheet data
        """
        payload = timesheet.model_dump(exclude_none=True, by_alias=True)

        if timesheet.begin:
            payload['begin'] = timesheet.begin.replace(microsecond=0).isoformat()
        if timesheet.end:
            payload['end'] = timesheet.end.replace(microsecond=0).isoformat()

        data = await self._request("POST", "/timesheets", json=payload)
        return TimesheetEntity(**data)
    
    async def update_timesheet(self, timesheet_id: int, timesheet: TimesheetEditForm) -> TimesheetEntity:
        """Update an existing timesheet.
        
        Args:
            timesheet_id: Timesheet ID to update
            timesheet: Updated timesheet data
        """
        payload = timesheet.model_dump(exclude_none=True, by_alias=True)

        if timesheet.begin:
            payload['begin'] = timesheet.begin.replace(microsecond=0).isoformat()
        if timesheet.end:
            payload['end'] = timesheet.end.replace(microsecond=0).isoformat()

        data = await self._request("PATCH", f"/timesheets/{timesheet_id}", json=payload)
        return TimesheetEntity(**data)
    
    async def delete_timesheet(self, timesheet_id: int) -> None:
        """Delete a timesheet."""
        await self._request("DELETE", f"/timesheets/{timesheet_id}")
    
    async def stop_timesheet(self, timesheet_id: int) -> TimesheetEntity:
        """Stop an active timesheet."""
        data = await self._request("PATCH", f"/timesheets/{timesheet_id}/stop")
        return TimesheetEntity(**data)
    
    async def restart_timesheet(self, timesheet_id: int, copy_all: bool = False, begin: Optional[datetime] = None) -> TimesheetEntity:
        """Restart a timesheet.
        
        Args:
            timesheet_id: Timesheet ID to restart
            copy_all: Whether to copy all data from original
            begin: Optional start time for new timesheet
        """
        payload = {}
        if copy_all:
            payload['copy'] = 'all'
        if begin:
            payload['begin'] = begin.replace(microsecond=0).isoformat()
        
        data = await self._request("PATCH", f"/timesheets/{timesheet_id}/restart", json=payload)
        return TimesheetEntity(**data)
    
    async def duplicate_timesheet(self, timesheet_id: int) -> TimesheetEntity:
        """Duplicate a timesheet."""
        data = await self._request("PATCH", f"/timesheets/{timesheet_id}/duplicate")
        return TimesheetEntity(**data)
    
    async def toggle_timesheet_export(self, timesheet_id: int) -> TimesheetEntity:
        """Toggle the export state of a timesheet."""
        data = await self._request("PATCH", f"/timesheets/{timesheet_id}/export")
        return TimesheetEntity(**data)
    
    async def update_timesheet_meta(self, timesheet_id: int, meta_field: MetaFieldForm) -> TimesheetEntity:
        """Update a timesheet's custom field."""
        payload = meta_field.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("PATCH", f"/timesheets/{timesheet_id}/meta", json=payload)
        return TimesheetEntity(**data)
    
    # Project endpoints
    
    async def get_projects(self, filters: Optional[ProjectFilter] = None) -> List[Project]:
        """Get list of projects.
        
        Args:
            filters: Project filters
        """
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)

            if filters.start:
                params['start'] = filters.start.isoformat()
            if filters.end:
                params['end'] = filters.end.isoformat()
                
            # Handle array parameters
            if filters.customers:
                params['customers[]'] = filters.customers
                del params['customers']
        
        data = await self._request("GET", "/projects", params=params)
        return [Project(**item) for item in data]
    
    async def get_project(self, project_id: int) -> Project:
        """Get a single project by ID."""
        data = await self._request("GET", f"/projects/{project_id}")
        return Project(**data)
    
    async def create_project(self, project: ProjectEditForm) -> ProjectExtended:
        """Create a new project."""
        payload = project.model_dump(exclude_none=True, by_alias=True)

        if project.start:
            payload['start'] = project.start.isoformat()
        if project.end:
            payload['end'] = project.end.isoformat()
        
        data = await self._request("POST", "/projects", json=payload)
        return ProjectExtended(**data)
    
    async def update_project(self, project_id: int, project: ProjectEditForm) -> ProjectExtended:
        """Update an existing project."""
        payload = project.model_dump(exclude_none=True, by_alias=True)

        if project.start:
            payload['start'] = project.start.isoformat()
        if project.end:
            payload['end'] = project.end.isoformat()

        data = await self._request("PATCH", f"/projects/{project_id}", json=payload)
        return ProjectExtended(**data)
    
    async def delete_project(self, project_id: int) -> None:
        """Delete a project (WARNING: Deletes ALL linked activities and timesheets)."""
        await self._request("DELETE", f"/projects/{project_id}")
    
    async def update_project_meta(self, project_id: int, meta_field: MetaFieldForm) -> ProjectExtended:
        """Update a project's custom field."""
        payload = meta_field.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("PATCH", f"/projects/{project_id}/meta", json=payload)
        return ProjectExtended(**data)
    
    async def get_project_rates(self, project_id: int) -> List[Rate]:
        """Get rates for a project."""
        data = await self._request("GET", f"/projects/{project_id}/rates")
        return [Rate(**item) for item in data]
    
    async def add_project_rate(self, project_id: int, rate: RateForm) -> Rate:
        """Add a rate for a project."""
        payload = rate.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("POST", f"/projects/{project_id}/rates", json=payload)
        return Rate(**data)
    
    async def delete_project_rate(self, project_id: int, rate_id: int) -> None:
        """Delete a rate for a project."""
        await self._request("DELETE", f"/projects/{project_id}/rates/{rate_id}")
    
    # Activity endpoints
    
    async def get_activities(self, filters: Optional[ActivityFilter] = None) -> List[Activity]:
        """Get list of activities.
        
        Args:
            filters: Activity filters
        """
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)
            
            # Handle array parameters
            if filters.projects:
                params['projects[]'] = filters.projects
                del params['projects']
        
        data = await self._request("GET", "/activities", params=params)
        return [Activity(**item) for item in data]
    
    async def get_activity(self, activity_id: int) -> Activity:
        """Get a single activity by ID."""
        data = await self._request("GET", f"/activities/{activity_id}")
        return Activity(**data)
    
    async def create_activity(self, activity: ActivityEditForm) -> ActivityExtended:
        """Create a new activity."""
        payload = activity.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("POST", "/activities", json=payload)
        return ActivityExtended(**data)
    
    async def update_activity(self, activity_id: int, activity: ActivityEditForm) -> ActivityExtended:
        """Update an existing activity."""
        payload = activity.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("PATCH", f"/activities/{activity_id}", json=payload)
        return ActivityExtended(**data)
    
    async def delete_activity(self, activity_id: int) -> None:
        """Delete an activity (WARNING: Deletes ALL linked timesheets)."""
        await self._request("DELETE", f"/activities/{activity_id}")
    
    async def update_activity_meta(self, activity_id: int, meta_field: MetaFieldForm) -> ActivityExtended:
        """Update an activity's custom field."""
        payload = meta_field.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("PATCH", f"/activities/{activity_id}/meta", json=payload)
        return ActivityExtended(**data)
    
    async def get_activity_rates(self, activity_id: int) -> List[Rate]:
        """Get rates for an activity."""
        data = await self._request("GET", f"/activities/{activity_id}/rates")
        return [Rate(**item) for item in data]
    
    async def add_activity_rate(self, activity_id: int, rate: RateForm) -> Rate:
        """Add a rate for an activity."""
        payload = rate.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("POST", f"/activities/{activity_id}/rates", json=payload)
        return Rate(**data)
    
    async def delete_activity_rate(self, activity_id: int, rate_id: int) -> None:
        """Delete a rate for an activity."""
        await self._request("DELETE", f"/activities/{activity_id}/rates/{rate_id}")
    
    # Customer endpoints
    
    async def get_customers(self, filters: Optional[CustomerFilter] = None) -> List[Customer]:
        """Get list of customers.
        
        Args:
            filters: Customer filters
        """
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)
        
        data = await self._request("GET", "/customers", params=params)
        return [Customer(**item) for item in data]
    
    async def get_customer(self, customer_id: int) -> Customer:
        """Get a single customer by ID."""
        data = await self._request("GET", f"/customers/{customer_id}")
        return Customer(**data)
    
    async def create_customer(self, customer: CustomerEditForm) -> CustomerExtended:
        """Create a new customer."""
        payload = customer.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("POST", "/customers", json=payload)
        return CustomerExtended(**data)
    
    async def update_customer(self, customer_id: int, customer: CustomerEditForm) -> CustomerExtended:
        """Update an existing customer."""
        payload = customer.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("PATCH", f"/customers/{customer_id}", json=payload)
        return CustomerExtended(**data)
    
    async def delete_customer(self, customer_id: int) -> None:
        """Delete a customer (WARNING: Deletes ALL linked projects, activities, and timesheets)."""
        await self._request("DELETE", f"/customers/{customer_id}")
    
    async def update_customer_meta(self, customer_id: int, meta_field: MetaFieldForm) -> CustomerExtended:
        """Update a customer's custom field."""
        payload = meta_field.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("PATCH", f"/customers/{customer_id}/meta", json=payload)
        return CustomerExtended(**data)
    
    async def get_customer_rates(self, customer_id: int) -> List[Rate]:
        """Get rates for a customer."""
        data = await self._request("GET", f"/customers/{customer_id}/rates")
        return [Rate(**item) for item in data]
    
    async def add_customer_rate(self, customer_id: int, rate: RateForm) -> Rate:
        """Add a rate for a customer."""
        payload = rate.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("POST", f"/customers/{customer_id}/rates", json=payload)
        return Rate(**data)
    
    async def delete_customer_rate(self, customer_id: int, rate_id: int) -> None:
        """Delete a rate for a customer."""
        await self._request("DELETE", f"/customers/{customer_id}/rates/{rate_id}")
    
    # Absence endpoints
    
    async def get_absences(self, filters: Optional[AbsenceFilter] = None) -> List[Absence]:
        """Get list of absences.

        Args:
            filters: Absence filters
        """
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)

        data = await self._request("GET", "/absences", params=params)
        return [Absence(**item) for item in data]
    
    async def create_absence(self, absence: AbsenceForm) -> List[Absence]:
        """Create a new absence (can create multiple for date ranges).
        
        Args:
            absence: Absence data
        """
        payload = absence.model_dump(exclude_none=True, by_alias=True)
        
        data = await self._request("POST", "/absences", json=payload)
        return [Absence(**item) for item in data]
    
    async def delete_absence(self, absence_id: int) -> None:
        """Delete an absence."""
        await self._request("DELETE", f"/absences/{absence_id}")
    
    async def request_absence_approval(self, absence_id: int) -> Absence:
        """Request approval for an absence."""
        data = await self._request("PATCH", f"/absences/{absence_id}/request")
        return Absence(**data)
    
    async def confirm_absence_approval(self, absence_id: int) -> Absence:
        """Confirm/approve an absence."""
        data = await self._request("PATCH", f"/absences/{absence_id}/confirm")
        return Absence(**data)
    
    async def reject_absence_approval(self, absence_id: int) -> Absence:
        """Reject an absence approval."""
        data = await self._request("PATCH", f"/absences/{absence_id}/reject")
        return Absence(**data)
    
    async def get_absence_types(self, language: Optional[str] = None) -> Dict[str, str]:
        """Get available absence types.
        
        Args:
            language: Language code for translations
        """
        params = {}
        if language:
            params["language"] = language
        
        return await self._request("GET", "/absences/types", params=params)
    
    async def get_absences_calendar(self, filters: Optional[AbsenceFilter] = None, language: Optional[str] = None) -> List[CalendarEvent]:
        """Get absences for calendar integration.
        
        Args:
            filters: Absence filters
            language: Language for display
        """
        params = {}
        if filters:
            params.update(filters.model_dump(exclude_none=True, by_alias=True))
        
        if language:
            params["language"] = language
        
        data = await self._request("GET", "/absences/calendar", params=params)
        return [CalendarEvent(**item) for item in data]
    
    # Working Contract endpoints
    
    async def unlock_work_contract_month(self, user_id: int, month: str) -> None:
        """Unlock working time months for a user.

        Args:
            user_id: User ID whose months to unlock
            month: Month in YYYY-MM-DD format (all months from this one to end of year will be unlocked)
        """
        await self._request("DELETE", f"/work-contract/unlock/{user_id}/{month}")

    async def lock_work_contract_month(self, user_id: int, month: str) -> None:
        """Lock working time months for a user.

        Locks all open months from the specified month back to the start of the given year.

        Args:
            user_id: User ID whose months to lock
            month: Month in YYYY-MM-DD format (all months before and including this one will be locked)
        """
        await self._request("DELETE", f"/work-contract/lock/{user_id}/{month}")

    # Public Holiday endpoints
    
    async def get_public_holidays(self, filters: Optional[PublicHolidayFilter] = None) -> List[PublicHoliday]:
        """Get list of public holidays.

        Args:
            filters: Public holiday filters
        """
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)

            if filters.begin:
                params['begin'] = filters.begin.date().isoformat()
            if filters.end:
                params['end'] = filters.end.date().isoformat()

        data = await self._request("GET", "/public-holidays", params=params)
        return [PublicHoliday(**item) for item in data]
    
    async def delete_public_holiday(self, holiday_id: int) -> None:
        """Delete a public holiday."""
        await self._request("DELETE", f"/public-holidays/{holiday_id}")
    
    async def get_public_holidays_calendar(self, filters: Optional[PublicHolidayFilter] = None) -> List[CalendarEvent]:
        """Get public holidays for calendar integration."""
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)

            if filters.begin:
                params['begin'] = filters.begin.date().isoformat()
            if filters.end:
                params['end'] = filters.end.date().isoformat()

        data = await self._request("GET", "/public-holidays/calendar", params=params)
        return [CalendarEvent(**item) for item in data]
    
    # Team endpoints
    
    async def get_teams(self) -> List[Team]:
        """Get list of teams."""
        data = await self._request("GET", "/teams")
        return [Team(**item) for item in data]
    
    async def get_team(self, team_id: int) -> Team:
        """Get a specific team by ID."""
        data = await self._request("GET", f"/teams/{team_id}")
        return Team(**data)
    
    async def create_team(self, team: TeamEditForm) -> Team:
        """Create a new team."""
        payload = team.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("POST", "/teams", json=payload)
        return Team(**data)
    
    async def update_team(self, team_id: int, team: TeamEditForm) -> Team:
        """Update an existing team."""
        payload = team.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("PATCH", f"/teams/{team_id}", json=payload)
        return Team(**data)
    
    async def delete_team(self, team_id: int) -> None:
        """Delete a team."""
        await self._request("DELETE", f"/teams/{team_id}")
    
    async def add_team_member(self, team_id: int, user_id: int) -> Team:
        """Add a member to a team."""
        data = await self._request("POST", f"/teams/{team_id}/members/{user_id}")
        return Team(**data)
    
    async def remove_team_member(self, team_id: int, user_id: int) -> Team:
        """Remove a member from a team."""
        data = await self._request("DELETE", f"/teams/{team_id}/members/{user_id}")
        return Team(**data)
    
    async def grant_team_customer_access(self, team_id: int, customer_id: int) -> Team:
        """Grant team access to a customer."""
        data = await self._request("POST", f"/teams/{team_id}/customers/{customer_id}")
        return Team(**data)
    
    async def revoke_team_customer_access(self, team_id: int, customer_id: int) -> Team:
        """Revoke team access to a customer."""
        data = await self._request("DELETE", f"/teams/{team_id}/customers/{customer_id}")
        return Team(**data)
    
    async def grant_team_project_access(self, team_id: int, project_id: int) -> Team:
        """Grant team access to a project."""
        data = await self._request("POST", f"/teams/{team_id}/projects/{project_id}")
        return Team(**data)
    
    async def revoke_team_project_access(self, team_id: int, project_id: int) -> Team:
        """Revoke team access to a project."""
        data = await self._request("DELETE", f"/teams/{team_id}/projects/{project_id}")
        return Team(**data)
    
    async def grant_team_activity_access(self, team_id: int, activity_id: int) -> Team:
        """Grant team access to an activity."""
        data = await self._request("POST", f"/teams/{team_id}/activities/{activity_id}")
        return Team(**data)
    
    async def revoke_team_activity_access(self, team_id: int, activity_id: int) -> Team:
        """Revoke team access to an activity."""
        data = await self._request("DELETE", f"/teams/{team_id}/activities/{activity_id}")
        return Team(**data)
    
    # Tag endpoints
    
    async def get_tags(self, filters: Optional[TagFilter] = None) -> List[str]:
        """Get list of tags as strings (deprecated endpoint)."""
        params = {}
        if filters and filters.name:
            params["name"] = filters.name
        
        return await self._request("GET", "/tags", params=params)
    
    async def get_tags_full(self, filters: Optional[TagFilter] = None) -> List[TagEntity]:
        """Get list of tag entities."""
        params = {}
        if filters and filters.name:
            params["name"] = filters.name
        
        data = await self._request("GET", "/tags/find", params=params)
        return [TagEntity(**item) for item in data]
    
    async def create_tag(self, tag: TagEditForm) -> TagEntity:
        """Create a new tag."""
        payload = tag.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("POST", "/tags", json=payload)
        return TagEntity(**data)
    
    async def delete_tag(self, tag_id: int) -> None:
        """Delete a tag."""
        await self._request("DELETE", f"/tags/{tag_id}")
    
    # Extended User endpoints
    
    async def get_users_extended(self, filters: Optional[UserFilter] = None) -> List[UserEntity]:
        """Get list of users with extended information.
        
        Args:
            filters: User filters
        """
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)
        
        data = await self._request("GET", "/users", params=params)
        return [UserEntity(**item) for item in data]
    
    async def get_user_extended(self, user_id: int) -> UserEntity:
        """Get extended user information by ID."""
        data = await self._request("GET", f"/users/{user_id}")
        return UserEntity(**data)
    
    async def create_user(self, user: UserCreateForm) -> UserEntity:
        """Create a new user."""
        payload = user.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("POST", "/users", json=payload)
        return UserEntity(**data)
    
    async def update_user(self, user_id: int, user: UserEditForm) -> UserEntity:
        """Update an existing user."""
        payload = user.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("PATCH", f"/users/{user_id}", json=payload)
        return UserEntity(**data)
    
    async def delete_api_token(self, token_id: int) -> Dict[str, Any]:
        """Delete an API token (only own tokens)."""
        return await self._request("DELETE", f"/users/api-token/{token_id}")
    
    # Invoice endpoints
    
    async def get_invoices(self, filters: Optional[InvoiceFilter] = None) -> List[Invoice]:
        """Get list of invoices.
        
        Args:
            filters: Invoice filters
        """
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)

            if filters.begin:
                params['begin'] = filters.begin.replace(microsecond=0).isoformat()
            if filters.end:
                params['end'] = filters.end.replace(microsecond=0).isoformat()
            
            # Handle array parameters
            if filters.customers:
                params['customers[]'] = filters.customers
                del params['customers']
            if filters.status:
                params['status[]'] = filters.status
                del params['status']
        
        data = await self._request("GET", "/invoices", params=params)
        return [Invoice(**item) for item in data]
    
    async def get_invoice(self, invoice_id: int) -> Invoice:
        """Get a specific invoice by ID."""
        data = await self._request("GET", f"/invoices/{invoice_id}")
        return Invoice(**data)