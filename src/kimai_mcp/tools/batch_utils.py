"""Utility functions for batch operations."""

import asyncio
from typing import List, Callable, Any, Tuple, TypeVar

# Rate limiting: max parallel requests to avoid overloading Kimai API
MAX_CONCURRENT = 10

T = TypeVar('T')


async def execute_batch(
    items: List[Any],
    operation: Callable[[Any], Any],
    max_concurrent: int = MAX_CONCURRENT
) -> Tuple[List[Any], List[Tuple[Any, str]]]:
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


def format_batch_result(
    operation_name: str,
    success: List[Any],
    failed: List[Tuple[Any, str]],
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
    result = f"Batch {operation_name} Complete\n"
    result += f"✓ {operation_name}d: {len(success)} {item_name}\n"

    if failed:
        result += f"✗ Failed: {len(failed)}\n"
        for item, error in failed[:max_errors_shown]:
            result += f"  - ID {item}: {error}\n"
        if len(failed) > max_errors_shown:
            result += f"  ... and {len(failed) - max_errors_shown} more\n"

    return result
