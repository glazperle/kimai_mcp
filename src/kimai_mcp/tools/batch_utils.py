"""Utility functions for batch operations."""

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from ..client import KimaiAPIError

# Rate limiting: max parallel requests to avoid overloading Kimai API
MAX_CONCURRENT = 10

T = TypeVar('T')


async def execute_batch(
    items: list[Any],
    operation: Callable[[Any], Any],
    max_concurrent: int = MAX_CONCURRENT
) -> tuple[list[Any], list[tuple[Any, str]]]:
    """Execute batch operation with concurrency control.

    Args:
        items: List of items to process
        operation: Async function to apply to each item
        max_concurrent: Maximum number of concurrent operations

    Returns:
        Tuple of (success_list, failed_list)
        - success_list: Results from successful operations
        - failed_list: List of (item, error_message) tuples for failures
    """
    if not items:
        return [], []

    # A repeated ID would run twice concurrently: a delete then reports a false
    # "Failed" (404), and a toggle (batch_export) undoes itself. (dispatch_tool
    # has already turned 1.0 into 1, so a float spelling cannot win here.)
    try:
        items = list(dict.fromkeys(items))
    except TypeError:
        pass  # unhashable items (models) are not IDs and are not repeated

    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited_operation(item: Any) -> Any:
        async with semaphore:
            return await operation(item)

    results = await asyncio.gather(
        *[limited_operation(item) for item in items],
        return_exceptions=True
    )

    success = []
    failed = []

    for item, result in zip(items, results):
        if isinstance(result, Exception):
            failed.append((item, str(result)))
        else:
            success.append(result)

    return success, failed


class _NotSentError(Exception):
    """A read left out because an earlier one failed (read_batch)."""


async def read_batch(
    items: list[Any],
    operation: Callable[[Any], Any],
    max_concurrent: int = MAX_CONCURRENT,
    *,
    route_may_be_missing: bool = False,
) -> tuple[list[Any], list[Any]]:
    """Run one read per item for an answer built from all of them.

    An item the token may not read (403) or that is gone (404) is skipped and
    returned, so the caller can say so. Any other failure (a 401, a timeout, a
    5xx) is raised: skipping it made "everyone's absences" or "all users" a
    confident answer that silently left people out. The reads not started yet
    are not sent then; each would fail the same way, with its retries.

    With ``route_may_be_missing`` (a plugin's route, such as /absences) a 404
    for every item is raised too: that is the route missing on this Kimai,
    not every item gone at once.

    Returns:
        Tuple of (results, skipped items)
    """
    errors: list[Exception] = []
    missing: list[KimaiAPIError] = []

    async def read(item: Any) -> Any:
        if errors:
            raise _NotSentError  # a fresh one: re-raising errors[0] grew its traceback per item
        try:
            return await operation(item)
        except KimaiAPIError as e:
            if e.status_code == 404:
                missing.append(e)
            elif e.status_code != 403:
                errors.append(e)
            raise
        except Exception as e:
            errors.append(e)
            raise

    success, failed = await execute_batch(items, read, max_concurrent)
    if errors:
        raise errors[0]
    if route_may_be_missing and missing and len(missing) == len(failed) and not success:
        raise missing[0]
    return success, [item for item, _ in failed]


def format_batch_result(
    operation_name: str,
    success: list[Any],
    failed: list[tuple[Any, str]],
    item_name: str = "items",
    max_errors_shown: int = 5
) -> str:
    """Format batch operation result as readable string.

    Args:
        operation_name: Name of the operation (e.g., "Delete", "Approve")
        success: List of successful results
        failed: List of (item, error) tuples
        item_name: Name of items being processed (e.g., "absences", "timesheets")
        max_errors_shown: Maximum number of errors to show in detail

    Returns:
        Formatted result string
    """
    past = operation_name + ("d" if operation_name.endswith("e") else "ed")  # Deleted, Exported
    result = f"Batch {operation_name} Complete\n"
    result += f"✓ {past}: {len(success)} {item_name}\n"

    if failed:
        result += f"✗ Failed: {len(failed)}\n"
        for item, error in failed[:max_errors_shown]:
            result += f"  - ID {item}: {error}\n"
        if len(failed) > max_errors_shown:
            result += f"  ... and {len(failed) - max_errors_shown} more\n"

    return result
