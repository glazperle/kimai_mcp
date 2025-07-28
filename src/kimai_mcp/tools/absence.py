"""Absence management tools for Kimai MCP.

Provides comprehensive absence tracking capabilities including:
- Individual user absence queries
- Cross-user absence analysis with statistics
- Flexible date and status filtering
- Calendar integration support
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp.types import Tool, TextContent

from ..client import KimaiClient
from ..models import AbsenceForm, AbsenceFilter


# Tool definitions

def list_absences_tool() -> Tool:
    """Define the absence listing tool with comprehensive analysis support."""
    return Tool(
        name="absence_list",
        description="List absences from specific user or all users with comprehensive analysis. Automatically queries all users individually when needed.",
        inputSchema={
            "type": "object",
            "properties": {
                "all_users": {
                    "type": "boolean", 
                    "description": "Set to true to analyze absences from all users with detailed statistics",
                    "default": False
                },
                "user": {"type": "string", "description": "Specific user ID to query (ignored if all_users is true)"},
                "begin": {"type": "string", "format": "date", "description": "Start date filter (YYYY-MM-DD)"},
                "end": {"type": "string", "format": "date", "description": "End date filter (YYYY-MM-DD)"},
                "status": {"type": "string", "enum": ["approved", "open", "all"], "description": "Status filter"}
            }
        }
    )


def get_absence_types_tool() -> Tool:
    """Define the get absence types tool."""
    return Tool(
        name="absence_types",
        description="Get available absence types",
        inputSchema={
            "type": "object",
            "properties": {
                "language": {"type": "string", "description": "Language code for translations (e.g., 'en', 'de')"}
            }
        }
    )


def calendar_absences_tool() -> Tool:
    """Define the calendar absences tool."""
    return Tool(
        name="calendar_absences",
        description="Get absences for calendar integration",
        inputSchema={
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "User ID to filter absences"},
                "begin": {"type": "string", "format": "date", "description": "Only absences after this date (YYYY-MM-DD)"},
                "end": {"type": "string", "format": "date", "description": "Only absences before this date (YYYY-MM-DD)"},
                "language": {"type": "string", "description": "Language code for display (e.g., 'en', 'de')"},
                "status": {"type": "string", "enum": ["approved", "open", "all"], "description": "Status filter"}
            }
        }
    )


def create_absence_tool() -> Tool:
    """Define the create absence tool."""
    return Tool(
        name="absence_create",
        description="Create a new absence entry",
        inputSchema={
            "type": "object",
            "required": ["comment", "date", "type"],
            "properties": {
                "comment": {"type": "string", "description": "Comment/reason for the absence"},
                "user": {"type": "integer", "description": "User ID (requires permission, defaults to current user)"},
                "date": {"type": "string", "format": "date", "description": "Start date of absence (YYYY-MM-DD)"},
                "end": {"type": "string", "format": "date", "description": "End date for multi-day absences (YYYY-MM-DD)"},
                "type": {"type": "string", "enum": ["holiday", "time_off", "sickness", "sickness_child", "other", "parental", "unpaid_vacation"], "description": "Type of absence"},
                "halfDay": {"type": "boolean", "description": "Whether this is a half-day absence"},
                "duration": {"type": "string", "description": "Duration in Kimai format (e.g., '04:00', '8h')"}
            }
        }
    )


def delete_absence_tool() -> Tool:
    """Define the delete absence tool."""
    return Tool(
        name="absence_delete",
        description="Delete an absence entry",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Absence ID to delete"}
            }
        }
    )


def approve_absence_tool() -> Tool:
    """Define the approve absence tool."""
    return Tool(
        name="absence_approve",
        description="Approve/confirm an absence request",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Absence ID to approve"}
            }
        }
    )


def reject_absence_tool() -> Tool:
    """Define the reject absence tool."""
    return Tool(
        name="absence_reject",
        description="Reject an absence request",
        inputSchema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "description": "Absence ID to reject"}
            }
        }
    )


# Tool handlers

async def handle_list_absences(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle absence listing requests.
    
    Supports both single-user queries and comprehensive multi-user analysis.
    When analyzing all users, queries each user individually as required by the API.
    """
    import asyncio
    from collections import defaultdict
    
    # Parse arguments
    analyze_all_users = arguments.get('all_users', False) if arguments else False
    user_id = arguments.get('user') if arguments else None
    begin_date = None
    end_date = None
    status_filter = None
    
    if arguments:
        if 'begin' in arguments:
            # Parse date and create datetime at start of day
            date_str = arguments['begin']
            begin_date = datetime.fromisoformat(f"{date_str}T00:00:00")
        if 'end' in arguments:
            # Parse date and create datetime at end of day
            date_str = arguments['end']
            end_date = datetime.fromisoformat(f"{date_str}T23:59:59")
        if 'status' in arguments:
            status_filter = arguments['status']
    
    all_absences = []
    
    if analyze_all_users:
        # Query all users individually (API requirement for cross-user data)
        try:
            users = await client.get_users()
            user_absence_tasks = []
            
            for user in users:
                filters = AbsenceFilter()
                filters.user = str(user.id)
                if begin_date:
                    filters.begin = begin_date
                if end_date:
                    filters.end = end_date
                if status_filter:
                    filters.status = status_filter
                
                # Create async task for each user
                user_absence_tasks.append(client.get_absences(filters))
            
            # Execute all user queries in parallel
            user_absence_results = await asyncio.gather(*user_absence_tasks, return_exceptions=True)
            
            # Collect all absences, handling any API errors gracefully
            for i, result in enumerate(user_absence_results):
                if isinstance(result, Exception):
                    # Log but continue - some users might not have permission
                    continue
                elif result:  # Only add if there are absences
                    all_absences.extend(result)
            
        except Exception as e:
            return [TextContent(
                type="text", 
                text=f"❌ Error during comprehensive analysis: {str(e)}\n\n**Tip:** This might be a permission issue. Ensure you have 'contract_other_profile' permission to view all users' absences."
            )]
    
    else:
        # Standard single-user query
        filters = AbsenceFilter()
        if user_id:
            filters.user = user_id
        if begin_date:
            filters.begin = begin_date
        if end_date:
            filters.end = end_date
        if status_filter:
            filters.status = status_filter
        
        all_absences = await client.get_absences(filters)
    
    if not all_absences:
        scope_info = "all users" if analyze_all_users else f"user {user_id}" if user_id else "current user"
        return [TextContent(type="text", text=f"No absences found for {scope_info} matching the criteria.")]
    
    # Sort by date for better analysis
    all_absences.sort(key=lambda x: x.date, reverse=True)
    
    # Generate comprehensive summary if requested
    if analyze_all_users:
        user_stats = defaultdict(lambda: {'total': 0, 'by_type': defaultdict(int), 'by_status': defaultdict(int)})
        
        for abs_entry in all_absences:
            user_key = f"{abs_entry.user.username} (ID: {abs_entry.user.id})"
            user_stats[user_key]['total'] += 1
            user_stats[user_key]['by_type'][abs_entry.type] += 1
            user_stats[user_key]['by_status'][abs_entry.status] += 1
        
        # Build comprehensive summary
        analysis_summary = [f"📊 **Comprehensive Absence Analysis** ({len(all_absences)} total absences from {len(user_stats)} users)\n"]
        
        # Sort users by total absences (most absent first)
        sorted_users = sorted(user_stats.items(), key=lambda x: x[1]['total'], reverse=True)
        
        for user, stats in sorted_users:
            analysis_summary.append(f"**{user}:** {stats['total']} absences")
            
            # Show breakdown by type
            type_breakdown = []
            for abs_type, count in stats['by_type'].items():
                type_icon = {"holiday": "🏖️", "sickness": "🤒", "time_off": "🆓", "other": "📝"}.get(abs_type, "📋")
                type_breakdown.append(f"{type_icon} {abs_type.replace('_', ' ')}: {count}")
            
            analysis_summary.append(f"  Types: {', '.join(type_breakdown)}")
            analysis_summary.append("")
        
        analysis_summary.append("---\n")
    
    # Format detailed results
    results = []
    for abs_entry in all_absences:
        status_icon = {"approved": "✅", "open": "⏳", "new": "🆕"}.get(abs_entry.status, "❓")
        type_icon = {"holiday": "🏖️", "sickness": "🤒", "time_off": "🆓", "other": "📝"}.get(abs_entry.type, "📋")
        half_day = " (Half Day)" if abs_entry.half_day else ""
        
        duration_str = ""
        if abs_entry.duration:
            hours = abs_entry.duration // 3600
            minutes = (abs_entry.duration % 3600) // 60
            duration_str = f" - {hours}h {minutes}m"
        
        result = f"""ID: {abs_entry.id} {status_icon} {type_icon}
User: {abs_entry.user.username} (ID: {abs_entry.user.id})
Date: {abs_entry.date.strftime('%Y-%m-%d')}{half_day}
Type: {abs_entry.type.replace('_', ' ').title()}
Status: {abs_entry.status.title()}{duration_str}
---"""
        results.append(result)
    
    # Build final response
    if analyze_all_users:
        summary = "\n".join(analysis_summary) + "\n".join(results)
    else:
        scope_info = f"user {user_id}" if user_id else "current user"
        summary = f"Found {len(all_absences)} absence(s) for {scope_info}:\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_calendar_absences(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle getting absences for calendar integration."""
    filters = AbsenceFilter()
    language = None
    
    if arguments:
        if 'user' in arguments:
            filters.user = arguments['user']
        if 'begin' in arguments:
            # Parse date and create datetime at start of day
            date_str = arguments['begin']
            filters.begin = datetime.fromisoformat(f"{date_str}T00:00:00")
        if 'end' in arguments:
            # Parse date and create datetime at end of day
            date_str = arguments['end']
            filters.end = datetime.fromisoformat(f"{date_str}T23:59:59")
        if 'status' in arguments:
            filters.status = arguments['status']
        if 'language' in arguments:
            language = arguments['language']
    
    calendar_events = await client.get_absences_calendar(filters, language)
    
    if not calendar_events:
        return [TextContent(type="text", text="No calendar events found matching the criteria.")]
    
    # Format results for calendar view
    results = []
    for event in calendar_events:
        all_day_str = " (All Day)" if event.all_day else ""
        start_date = event.start.strftime('%Y-%m-%d %H:%M') if event.start else "Unknown"
        end_date = event.end.strftime('%Y-%m-%d %H:%M') if event.end else "Ongoing"
        
        result = f"""📅 {event.title}{all_day_str}
Start: {start_date}
End: {end_date}
Color: {event.color or 'Default'}
---"""
        results.append(result)
    
    summary = f"Found {len(calendar_events)} calendar event(s):\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_get_absence_types(client: KimaiClient, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent]:
    """Handle getting absence types."""
    language = arguments.get('language') if arguments else None
    types = await client.get_absence_types(language)
    
    if not types:
        return [TextContent(type="text", text="No absence types configured.")]
    
    results = []
    for key, name in types.items():
        icon = {"holiday": "🏖️", "sickness": "🤒", "time_off": "🆓", "other": "📝", "parental": "👶", "unpaid_vacation": "💸"}.get(key, "📋")
        results.append(f"{icon} {key}: {name}")
    
    summary = f"Available absence types:\n\n" + "\n".join(results)
    
    return [TextContent(type="text", text=summary)]


async def handle_create_absence(client: KimaiClient, arguments: Dict[str, Any], default_user_id: Optional[str] = None) -> List[TextContent]:
    """Handle creating an absence."""
    form_data = {
        'comment': arguments['comment'],
        'date': arguments['date'],
        'type': arguments['type']
    }
    
    # Optional fields
    if 'end' in arguments:
        form_data['end'] = arguments['end']
    if 'halfDay' in arguments:
        form_data['half_day'] = arguments['halfDay']
    if 'duration' in arguments:
        form_data['duration'] = arguments['duration']
    
    # User handling
    if 'user' in arguments:
        form_data['user'] = arguments['user']
    elif default_user_id:
        form_data['user'] = int(default_user_id)
    else:
        # Get current user
        current_user = await client.get_current_user()
        form_data['user'] = current_user.id
    
    absence_form = AbsenceForm(**form_data)
    absences = await client.create_absence(absence_form)
    
    if len(absences) == 1:
        abs_entry = absences[0]
        type_icon = {"holiday": "🏖️", "sickness": "🤒", "time_off": "🆓", "other": "📝"}.get(abs_entry.type, "📋")
        
        result = f"""Absence created successfully! {type_icon}
ID: {abs_entry.id}
Date: {abs_entry.date.strftime('%Y-%m-%d')}
Type: {abs_entry.type.replace('_', ' ').title()}
Status: {abs_entry.status.title()}
Comment: {arguments['comment']}"""
    else:
        result = f"Created {len(absences)} absence entries for the date range."
    
    return [TextContent(type="text", text=result)]


async def handle_delete_absence(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle deleting an absence."""
    absence_id = arguments['id']
    await client.delete_absence(absence_id)
    
    return [TextContent(type="text", text=f"Absence #{absence_id} deleted successfully.")]


async def handle_approve_absence(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle approving an absence."""
    absence_id = arguments['id']
    abs_entry = await client.confirm_absence_approval(absence_id)
    
    result = f"""Absence #{abs_entry.id} approved successfully! ✅
User: {abs_entry.user.username}
Date: {abs_entry.date.strftime('%Y-%m-%d')}
Type: {abs_entry.type.replace('_', ' ').title()}
Status: {abs_entry.status.title()}"""
    
    return [TextContent(type="text", text=result)]


async def handle_reject_absence(client: KimaiClient, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle rejecting an absence."""
    absence_id = arguments['id']
    abs_entry = await client.reject_absence_approval(absence_id)
    
    result = f"""Absence #{abs_entry.id} rejected. ❌
User: {abs_entry.user.username}
Date: {abs_entry.date.strftime('%Y-%m-%d')}
Type: {abs_entry.type.replace('_', ' ').title()}
Status: {abs_entry.status.title()}"""
    
    return [TextContent(type="text", text=result)]