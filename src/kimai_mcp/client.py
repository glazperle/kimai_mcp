"""Kimai API client wrapper."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .models import (
    Absence,
    AbsenceFilter,
    AbsenceForm,
    AccessTokenCreated,
    AccessTokenInfo,
    Activity,
    ActivityEditForm,
    ActivityExtended,
    ActivityFilter,
    CalendarEvent,
    Comment,
    CommentForm,
    Customer,
    CustomerEditForm,
    CustomerExtended,
    CustomerFilter,
    Invoice,
    InvoiceEditForm,
    InvoiceFilter,
    MetaFieldForm,
    Plugin,
    Project,
    ProjectEditForm,
    ProjectExtended,
    ProjectFilter,
    PublicHoliday,
    PublicHolidayFilter,
    Rate,
    RateForm,
    TagEditForm,
    TagEntity,
    TagFilter,
    Team,
    TeamEditForm,
    TimesheetConfig,
    TimesheetEditForm,
    TimesheetEntity,
    TimesheetExpanded,
    TimesheetFilter,
    User,
    UserCreateForm,
    UserEditForm,
    UserEntity,
    UserFilter,
    Version,
)

logger = logging.getLogger(__name__)

# Largest page Kimai serves (BaseApiController::MAX_PAGE_SIZE); larger sizes are capped.
MAX_PAGE_SIZE = 500


@dataclass
class TimesheetPage:
    """One page of GET /timesheets and what Kimai's headers say about the rest.

    ``total`` and ``total_pages`` come from ``X-Total-Count`` and
    ``X-Total-Pages`` (``src/API/ViewHandler.php``); they are ``None`` when a
    proxy dropped the headers.
    """

    rows: list[TimesheetEntity]
    page: int
    size: int
    total: int | None = None
    total_pages: int | None = None

    @property
    def has_more(self) -> bool:
        if self.total_pages is not None:
            return self.page < self.total_pages
        return len(self.rows) >= self.size


class KimaiAPIError(Exception):
    """Kimai API error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        details: Any | None = None,
        method: str | None = None,
        endpoint: str | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details
        # Which request failed, so format_api_error() can give hints that only
        # make sense for one endpoint family (e.g. the project lock date on
        # timesheet writes) without attaching them to every 403.
        self.method = method
        self.endpoint = endpoint
        super().__init__(self.message)


def _query_for_log(kwargs: dict) -> str:
    """The query string of a request, for a log line; never the body.

    A write's body can hold a new user's ``plainPassword`` and
    ``plainApiToken``, and the log goes to a file and, on the streamable
    server, to every user's shared log.
    """
    params = kwargs.get("params")
    return f" with params {params}" if params else ""


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    """A non-negative integer header (ASCII digits only), else None."""
    value = headers.get(name)
    return int(value) if value is not None and value.isascii() and value.isdigit() else None


def _prune_empty_dicts(obj: Any) -> Any:
    """Drop keys whose value is an empty dict, recursively.

    Kimai's form-error envelope nests one entry per form field, most of them
    empty; without this the useful message drowns in braces.
    """
    if isinstance(obj, dict):
        pruned = {k: _prune_empty_dicts(v) for k, v in obj.items()}
        return {k: v for k, v in pruned.items() if not (isinstance(v, dict) and len(v) == 0)}
    if isinstance(obj, list):
        return [_prune_empty_dicts(v) for v in obj]
    return obj


def _as_validation_envelope(data: Any) -> tuple[str, int, Any] | None:
    """Return (message, code, details) if ``data`` is an error envelope.

    Kimai returns ``{"code": 400, "message": "Validation Failed", "errors":
    {...}}``. On some endpoints it does so with an HTTP status that says
    success, so the body is the only signal. No entity response carries a
    top-level integer ``code`` >= 400 next to a string ``message``.
    """
    if not isinstance(data, dict):
        return None
    code = data.get("code")
    message = data.get("message")
    if not isinstance(code, int) or isinstance(code, bool) or code < 400:
        return None
    if not isinstance(message, str):
        return None
    details = _prune_empty_dicts(data.get("errors", data))
    return message, code, details


class KimaiClient:
    """Kimai API client."""

    def __init__(self, base_url: str, api_token: str, timeout: float = 30.0,
                 ssl_verify: bool | str = True):
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
        # Projects GET /projects/{id} answered 403 for: it needs 'view' on that
        # project (view_project, or view_teamlead_project for a team's own), so
        # a second analysis of the same project goes to the listing directly.
        self.denied_project_views: set[int] = set()
        # Set once GET /users answered 403: view_user is a super-admin
        # permission by default, so the name lookups stop asking.
        self.users_list_denied = False
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
    
    # A read is retried on these: rate limiting, and what a proxy answers
    # while Kimai restarts. Not 504: a gateway that timed out waiting for a
    # slow Kimai would only send it the same request again.
    RETRY_STATUSES = frozenset({429, 502, 503})
    # Seconds before the 2nd and 3rd attempt; a Retry-After header wins.
    RETRY_DELAYS = (0.5, 1.5)
    # A Retry-After beyond this is not waited for: the retries would fail the
    # same way, and the caller's own timeout runs out first.
    MAX_RETRY_AFTER = 10.0
    # A connection that broke after it was established (a reset, or a reused
    # keep-alive connection the server had closed). Not a refused connection,
    # an unknown host or a timeout: each retry of those costs up to `timeout`
    # again and fails the same way.
    RETRY_ERRORS = (httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float | None:
        """Seconds to wait before the next attempt, or None not to retry.

        ``Retry-After`` is seconds or an HTTP date (RFC 9110); an unreadable
        one falls back to the fixed delay.
        """
        header = response.headers.get("Retry-After")
        if header is None:
            return self.RETRY_DELAYS[attempt]
        try:
            seconds = float(header)
        except ValueError:
            try:
                when = parsedate_to_datetime(header)
            except (TypeError, ValueError):
                return self.RETRY_DELAYS[attempt]
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - datetime.now(timezone.utc)).total_seconds()
        seconds = max(seconds, 0.0)
        return seconds if seconds <= self.MAX_RETRY_AFTER else None  # NaN and inf too

    async def _send(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """Send one request; a GET is retried on a transient failure.

        Only reads are retried. A POST, PATCH or DELETE that timed out or got
        a 502 may still have reached Kimai, and repeating it could create a
        record twice or toggle a flag back. A read timeout is not retried
        either (see RETRY_ERRORS).
        """
        attempts = len(self.RETRY_DELAYS) + 1 if method == "GET" else 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = await self._client.request(method, endpoint, **kwargs)
            except self.RETRY_ERRORS as e:
                if last:
                    raise
                logger.warning(f"{method} {endpoint} failed ({e!s}); retrying")
                await asyncio.sleep(self.RETRY_DELAYS[attempt])
                continue
            if response.status_code in self.RETRY_STATUSES and not last:
                delay = self._retry_delay(response, attempt)
                if delay is not None:
                    logger.warning(f"{method} {endpoint} answered {response.status_code}; retrying")
                    await asyncio.sleep(delay)
                    continue
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict | list:
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
        data, _headers = await self._request_with_headers(method, endpoint, **kwargs)
        return data

    async def _request_with_headers(self, method: str, endpoint: str, **kwargs) -> tuple[dict | list, httpx.Headers]:
        """Like :meth:`_request`, plus the response headers (pagination)."""
        try:
            response = await self._send(method, endpoint, **kwargs)
            response.raise_for_status()

            if response.status_code == 204:
                return {}, response.headers

            data = response.json()

            # An invalid PATCH does not necessarily arrive as a 4xx: Kimai
            # answers with the serialized form and HTTP 200 for timesheets,
            # users and teams (TimesheetController::patchAction and friends do
            # `new View($form, Response::HTTP_OK)`; customers and activities
            # were changed to 400 in 2.66). Without this check the envelope is
            # fed to the response model and surfaces as a raw pydantic error
            # instead of the API message, so none of the hints in
            # format_api_error() ever reach the user on an update.
            envelope = _as_validation_envelope(data)
            if envelope is not None:
                message, code, error_details = envelope
                logger.error(
                    f"API error: {message} for request {method} {endpoint} "
                    f"(HTTP {response.status_code} with an error envelope)"
                    + (f" | details: {error_details}" if error_details else "")
                )
                raise KimaiAPIError(
                    message, code, details=error_details, method=method, endpoint=endpoint
                )

            return data, response.headers

        except httpx.HTTPStatusError as e:
            # Try to parse error response
            error_details: Any | None = None
            try:
                error_data = e.response.json()
                message = error_data.get('message', str(e))

                # Extract errors if present and prune empty dicts
                if isinstance(error_data, dict):
                    if 'errors' in error_data:
                        error_details = _prune_empty_dicts(error_data['errors'])
                    else:
                        # Fallback to full payload (pruned) for context
                        error_details = _prune_empty_dicts(error_data)
                else:
                    error_details = None
            except (ValueError, AttributeError):
                # Body was not JSON, or not the object shape we expect.
                message = str(e)
                error_details = None

            # A 4xx is Kimai's answer to this request (a missing permission is
            # routine for the best-effort lookups); the caller reports it.
            log = logger.warning if e.response.status_code < 500 else logger.error
            log(
                f"API error: {message} for request {method} {endpoint}{_query_for_log(kwargs)}"
                + (f" | details: {error_details}" if error_details else "")
            )

            raise KimaiAPIError(
                message, e.response.status_code, details=error_details, method=method, endpoint=endpoint
            )
        except httpx.RequestError as e:
            logger.error(f"API error: {e!s} for request {method} {endpoint}{_query_for_log(kwargs)}")
            raise KimaiAPIError(f"Request failed: {e!s}")

    # Version and status endpoints

    async def get_version(self) -> Version:
        """Get Kimai version information."""
        data = await self._request("GET", "/version")
        return Version(**data)

    async def ping(self) -> dict[str, str]:
        """Ping the API to test connectivity."""
        return await self._request("GET", "/ping")

    # Configuration endpoints

    async def get_timesheet_config(self) -> TimesheetConfig:
        """Get timesheet configuration.

        Returns tracking mode, limits, and rules for timesheets.
        """
        data = await self._request("GET", "/config/timesheet")
        return TimesheetConfig(**data)

    async def get_color_config(self) -> dict[str, str]:
        """Get configured color codes.

        Returns a mapping of color names to hex codes.
        """
        return await self._request("GET", "/config/colors")

    async def get_plugins(self) -> list[Plugin]:
        """Get list of installed plugins."""
        data = await self._request("GET", "/plugins")
        return [Plugin(**item) for item in data]

    # User endpoints

    async def get_current_user(self) -> UserEntity:
        """Get current authenticated user (``UserEntity``: roles, teams, preferences)."""
        data = await self._request("GET", "/users/me")
        return UserEntity(**data)

    async def get_users(self, filters: UserFilter | None = None) -> list[User]:
        """Get list of users (needs ``view_user``, a super-admin permission by default).

        Args:
            filters: visible (1 visible, 2 hidden, 3 all), term, order_by, order, full
        """
        params = (filters or UserFilter()).model_dump(exclude_none=True, by_alias=True)
        data = await self._request("GET", "/users", params=params)
        return [User(**item) for item in data]

    # Timesheet endpoints

    @staticmethod
    def _timesheet_params(filters: TimesheetFilter | None) -> dict[str, Any]:
        """Query parameters of GET /timesheets for ``filters``."""
        if not filters:
            return {}
        params = filters.model_dump(exclude_none=True, by_alias=True)
        # Local date-times without microseconds: Kimai takes Y-m-d\TH:i:s only.
        for key in ("begin", "end", "modified_after"):
            value = getattr(filters, key)
            if isinstance(value, datetime):
                params[key] = value.replace(microsecond=0).isoformat()
        # Kimai caps the page size at 500; a larger one would make a capped
        # page look like the last one.
        if "size" in params:
            params["size"] = min(params["size"], MAX_PAGE_SIZE)
        for key in ("users", "customers", "projects", "activities", "tags"):
            if key in params:
                params[f"{key}[]"] = params.pop(key)
        return params

    async def get_timesheet_page(self, filters: TimesheetFilter) -> TimesheetPage:
        """One page of GET /timesheets, with Kimai's pagination headers.

        ``filters.page`` defaults to 1. With ``filters.full`` set, the rows are
        the Expanded schema (project, activity and user as objects, so they
        can be named). Kimai answers a page past the end with 404.
        """
        params = self._timesheet_params(filters)
        params.setdefault("page", 1)
        data, headers = await self._request_with_headers("GET", "/timesheets", params=params)
        expanded = str(filters.full).lower() in ("1", "true")

        def header(name: str) -> int | None:
            return _int_header(headers, name)

        return TimesheetPage(
            rows=[TimesheetExpanded(**item) if expanded else TimesheetEntity(**item) for item in data],
            page=params["page"],
            size=params.get("size", 50),
            total=header("X-Total-Count"),
            total_pages=header("X-Total-Pages"),
        )

    async def get_timesheets(
        self,
        filters: TimesheetFilter | None = None,
        max_results: int | None = None,
    ) -> tuple[list[TimesheetEntity], bool]:
        """Every page of GET /timesheets for ``filters``.

        One page, with Kimai's totals and the Expanded rows of ``full``, is
        what :meth:`get_timesheet_page` is for.

        Args:
            filters: Timesheet filters; ``size`` is the page size (up to 500),
                ``page`` is ignored.
            max_results: Stop once this many records were collected.

        Returns:
            The records, and whether that is all of them (False when
            ``max_results`` or the page cap stopped the loop).
        """
        params = self._timesheet_params(filters)
        # These rows are parsed as TimesheetEntity; full=true would send the
        # Expanded shape (objects for the relations).
        params.pop("full", None)
        page_size = params.get("size", 50)

        all_timesheets = []
        seen: set = set()
        page = 1
        fetched_all = True

        while True:
            paginated_params = {**params, "page": page, "size": page_size}

            total_pages = None
            try:
                data, headers = await self._request_with_headers("GET", "/timesheets", params=paginated_params)
                total_pages = _int_header(headers, "X-Total-Pages")
            except KimaiAPIError as e:
                # Kimai answers an out-of-range page with 404 on the API (it
                # only clamps the page for UI queries, src/Utils/Pagination.php).
                # Paging past a full last page is how this loop finds the end,
                # so only that 404 is swallowed; page 1 still raises.
                if e.status_code != 404 or page == 1:
                    raise
                data = []

            if not data:
                break

            # A record seen on an earlier page is skipped: Kimai's count and
            # pages repeat records for some meta searches ('name:~').
            for item in data:
                if item.get("id") is None or item["id"] not in seen:
                    seen.add(item.get("id"))
                    all_timesheets.append(TimesheetEntity(**item))

            # The last page: Kimai says so, or it is not full.
            if (total_pages is not None and page >= total_pages) or len(data) < page_size:
                break

            if max_results is not None and len(all_timesheets) >= max_results:
                fetched_all = False
                break

            # Safety cap, for a caller without max_results.
            if page >= 100:
                fetched_all = False
                break

            page += 1

        return all_timesheets, fetched_all
    
    async def get_active_timesheets(self) -> list[TimesheetExpanded]:
        """Get active timesheets for current user.

        Kimai declares this endpoint as ``TimesheetCollectionExpanded``, so the
        relations arrive as objects rather than ids (issue #24).
        """
        data = await self._request("GET", "/timesheets/active")
        return [TimesheetExpanded(**item) for item in data]

    async def get_recent_timesheets(self, begin: datetime | None = None, size: int = 10) -> list[TimesheetExpanded]:
        """Get recent timesheet activities.

        Declared as ``TimesheetCollectionExpanded`` like ``/timesheets/active``,
        so the relations arrive expanded here too.

        Args:
            begin: Only records after this date
            size: Number of entries to return
        """
        params = {"size": size}
        if begin:
            params["begin"] = begin.replace(microsecond=0).isoformat()

        data = await self._request("GET", "/timesheets/recent", params=params)
        return [TimesheetExpanded(**item) for item in data]
    
    # Favorites (Kimai 2.66+, #6143). All three need start_own_timesheet and
    # work on the current user's own records only.
    async def get_favorite_timesheets(self) -> list[TimesheetExpanded]:
        """Timesheets the current user marked as favorites (templates for ``restart``).

        Declared as ``TimesheetCollectionExpanded``, so relations are objects.
        """
        data = await self._request("GET", "/favorites/timesheets")
        return [TimesheetExpanded(**item) for item in data]

    async def add_favorite_timesheet(self, timesheet_id: int) -> None:
        """Mark one of the user's own timesheets as favorite. Idempotent on Kimai's side (204)."""
        await self._request("POST", f"/favorites/timesheets/{timesheet_id}")

    async def remove_favorite_timesheet(self, timesheet_id: int) -> None:
        """Remove a timesheet from the favorites. Not an error if it was none (204)."""
        await self._request("DELETE", f"/favorites/timesheets/{timesheet_id}")

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
    
    async def restart_timesheet(self, timesheet_id: int, copy_all: bool = False, begin: datetime | None = None) -> TimesheetEntity:
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
    
    async def get_projects(self, filters: ProjectFilter | None = None) -> list[Project]:
        """Get list of projects.
        
        Args:
            filters: Project filters
        """
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)

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

        data = await self._request("POST", "/projects", json=payload)
        return ProjectExtended(**data)
    
    async def update_project(self, project_id: int, project: ProjectEditForm) -> ProjectExtended:
        """Update an existing project."""
        payload = project.model_dump(exclude_none=True, by_alias=True)

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
    
    async def get_project_rates(self, project_id: int) -> list[Rate]:
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
    
    async def get_activities(self, filters: ActivityFilter | None = None) -> list[Activity]:
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
    
    async def get_activity_rates(self, activity_id: int) -> list[Rate]:
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
    
    async def get_customers(self, filters: CustomerFilter | None = None) -> list[Customer]:
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
    
    async def get_customer_rates(self, customer_id: int) -> list[Rate]:
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
    
    async def get_absences(self, filters: AbsenceFilter | None = None) -> list[Absence]:
        """Get list of absences.

        Args:
            filters: Absence filters
        """
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)

        data = await self._request("GET", "/absences", params=params)
        return [Absence(**item) for item in data]
    
    async def create_absence(self, absence: AbsenceForm) -> list[Absence]:
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
    
    async def get_absence_types(self, language: str | None = None) -> dict[str, str]:
        """Get available absence types.
        
        Args:
            language: Language code for translations
        """
        params = {}
        if language:
            params["language"] = language
        
        return await self._request("GET", "/absences/types", params=params)
    
    async def get_absences_calendar(self, filters: AbsenceFilter | None = None, language: str | None = None) -> list[CalendarEvent]:
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
    
    async def get_public_holidays(self, filters: PublicHolidayFilter | None = None) -> list[PublicHoliday]:
        """Get list of public holidays.

        Args:
            filters: Public holiday filters
        """
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)

            # Kimai rejects date-only values here (400); it requires a full
            # ISO datetime (YYYY-MM-DDTHH:MM:SS), like the other list endpoints.
            if filters.begin:
                params['begin'] = filters.begin.replace(microsecond=0).isoformat()
            if filters.end:
                params['end'] = filters.end.replace(microsecond=0).isoformat()

        data = await self._request("GET", "/public-holidays", params=params)
        return [PublicHoliday(**item) for item in data]
    
    async def delete_public_holiday(self, holiday_id: int) -> None:
        """Delete a public holiday."""
        await self._request("DELETE", f"/public-holidays/{holiday_id}")
    
    async def get_public_holidays_calendar(self, filters: PublicHolidayFilter | None = None) -> list[CalendarEvent]:
        """Get public holidays for calendar integration."""
        params = {}
        if filters:
            params = filters.model_dump(exclude_none=True, by_alias=True)

            # Full ISO datetime required (date-only returns 400).
            if filters.begin:
                params['begin'] = filters.begin.replace(microsecond=0).isoformat()
            if filters.end:
                params['end'] = filters.end.replace(microsecond=0).isoformat()

        data = await self._request("GET", "/public-holidays/calendar", params=params)
        return [CalendarEvent(**item) for item in data]
    
    # Team endpoints
    
    async def get_teams(self) -> list[Team]:
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
    
    async def get_tags_full(self, filters: TagFilter | None = None) -> list[TagEntity]:
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

    async def update_user_preferences(
        self,
        user_id: int,
        preferences: list[dict[str, Any]]
    ) -> UserEntity:
        """Update user preferences (e.g., work contract settings).

        Args:
            user_id: The user ID
            preferences: List of {"name": "...", "value": "..."} dicts.
                Common preferences for work contracts:
                - work_contract_type: "week" or "day"
                - hours_per_week: Total weekly hours in seconds (144000 = 40h)
                - work_monday..work_sunday: Daily hours in seconds (28800 = 8h)
                - holidays: Vacation days per year
                - public_holiday_group: Holiday group ID
                - work_start_day/work_last_day: Contract period (YYYY-MM-DD)

        Returns:
            Updated UserEntity with all preferences
        """
        data = await self._request(
            "PATCH",
            f"/users/{user_id}/preferences",
            json=preferences
        )
        return UserEntity(**data)

    async def delete_api_token(self, token_id: int) -> dict[str, Any]:
        """Delete an API token (only own tokens)."""
        return await self._request("DELETE", f"/users/api-token/{token_id}")

    async def create_api_token(
        self,
        user_id: int,
        name: str,
        expires_at: str | None = None,
        replace_existing: bool = True,
    ) -> AccessTokenCreated:
        """Create an API token for a user and return it (shown only once).

        Requires the ``ApiTokenBundle`` plugin (``kimai-plugin/ApiTokenBundle``)
        on the Kimai server; core Kimai can only create tokens through its web
        UI. The calling token must belong to a user holding
        ``api-token_other_profile`` (ROLE_SUPER_ADMIN by default) unless it is
        creating a token for its own account.

        Raises:
            KimaiAPIError: 404 if the plugin is not installed, 403 if the
                calling token lacks the permission.
        """
        payload: dict[str, Any] = {"name": name, "replaceExisting": replace_existing}
        if expires_at:
            payload["expiresAt"] = expires_at
        data = await self._request("POST", f"/users/{user_id}/api-token", json=payload)
        return AccessTokenCreated(**data)

    async def get_api_tokens(self, user_id: int) -> list[AccessTokenInfo]:
        """List a user's API token metadata (never the token value).

        Requires the ``ApiTokenBundle`` plugin, see :meth:`create_api_token`.
        """
        data = await self._request("GET", f"/users/{user_id}/api-token")
        return [AccessTokenInfo(**item) for item in data]


    # Invoice endpoints
    
    async def get_invoices(self, filters: InvoiceFilter | None = None) -> list[Invoice]:
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

    async def update_invoice(self, invoice_id: int, invoice: InvoiceEditForm) -> Invoice:
        """Update status, payment date or comment of an invoice (Kimai 2.68+, permission edit_invoice)."""
        payload = invoice.model_dump(exclude_none=True, by_alias=True)
        data = await self._request("PATCH", f"/invoices/{invoice_id}", json=payload)
        return Invoice(**data)

    async def delete_invoice(self, invoice_id: int) -> None:
        """Delete an invoice and its generated document (Kimai 2.66+, permission delete_invoice)."""
        await self._request("DELETE", f"/invoices/{invoice_id}")

    async def update_invoice_meta(self, invoice_id: int, meta_fields: list[MetaFieldForm]) -> Invoice:
        """Update meta fields of an invoice (requires Kimai 2.56+).

        Unlike the other meta endpoints, this one accepts an array of fields in a single request.
        """
        payload = [field.model_dump(exclude_none=True) for field in meta_fields]
        data = await self._request("PATCH", f"/invoices/{invoice_id}/custom-fields", json=payload)
        return Invoice(**data)

    # Comment endpoints (requires Kimai 2.57+).
    # `entity` is "project" or "customer"; the path segment is the plural form.

    async def get_comments(self, entity: str, entity_id: int) -> list[Comment]:
        """Get comments for a project or customer."""
        data = await self._request("GET", f"/{entity}s/{entity_id}/comments")
        return [Comment(**item) for item in data]

    async def create_comment(self, entity: str, entity_id: int, form: CommentForm) -> Comment:
        """Add a comment to a project or customer."""
        data = await self._request("POST", f"/{entity}s/{entity_id}/comments",
                                   json=form.model_dump(exclude_none=True))
        return Comment(**data)

    async def delete_comment(self, entity: str, entity_id: int, comment_id: int) -> None:
        """Delete a project or customer comment."""
        await self._request("DELETE", f"/{entity}s/{entity_id}/comments/{comment_id}")

    async def pin_comment(self, entity: str, entity_id: int, comment_id: int) -> Comment:
        """Toggle the pinned status of a project or customer comment."""
        data = await self._request("PATCH", f"/{entity}s/{entity_id}/comments/{comment_id}/pin")
        return Comment(**data)