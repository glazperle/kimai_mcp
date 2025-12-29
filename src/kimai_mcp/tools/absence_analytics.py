"""Analytics extension for absence calculations."""

from typing import Dict, List, Any
from collections import defaultdict
from datetime import datetime


class AbsenceAnalytics:
    """Performs calculations on absence data."""

    # Absence type translations (German)
    TYPE_LABELS = {
        "holiday": "Urlaub",
        "sickness": "Krankheit",
        "sickness_child": "Kind krank",
        "time_off": "Zeitausgleich",
        "parental": "Elternzeit",
        "unpaid_vacation": "Unbezahlter Urlaub",
        "other": "Sonstiges"
    }

    @staticmethod
    def calculate_statistics(
        absences: List[Any],
        group_by: str = "type",
        breakdown_by_month: bool = False
    ) -> Dict[str, Any]:
        """Calculate comprehensive statistics from absence data.

        Args:
            absences: List of absence entities
            group_by: Group results by "type", "user", or "month"
            breakdown_by_month: Include monthly breakdown

        Returns:
            Dictionary with statistics
        """
        if not absences:
            return {
                "total_entries": 0,
                "total_days": 0,
                "message": "No absences found for analysis"
            }

        stats = {
            "total_entries": len(absences),
            "total_days": 0,
            "unique_users": set(),
            "by_type": defaultdict(lambda: {"count": 0, "days": 0, "users": set()}),
            "by_user": defaultdict(lambda: {"count": 0, "days": 0, "types": defaultdict(int), "username": ""}),
            "by_month": defaultdict(lambda: {"count": 0, "days": 0, "types": defaultdict(int)}),
            "by_status": defaultdict(int),
        }

        for absence in absences:
            # Calculate days (duration is in seconds, 1 day = 28800 seconds for 8h workday)
            duration_seconds = getattr(absence, 'duration', 0) or 0
            # Assume 8 hours = 1 day, so 28800 seconds = 1 day
            days = duration_seconds / 28800 if duration_seconds > 0 else 1

            # Get absence info
            absence_type = getattr(absence, 'type', 'other') or 'other'
            user = getattr(absence, 'user', None)
            user_id = user.id if user else 0
            username = user.username if user else "Unknown"
            status = getattr(absence, 'status', 'unknown') or 'unknown'
            date = getattr(absence, 'date', None)

            # Update totals
            stats["total_days"] += days
            stats["unique_users"].add(user_id)

            # By type
            stats["by_type"][absence_type]["count"] += 1
            stats["by_type"][absence_type]["days"] += days
            stats["by_type"][absence_type]["users"].add(user_id)

            # By user
            stats["by_user"][user_id]["count"] += 1
            stats["by_user"][user_id]["days"] += days
            stats["by_user"][user_id]["types"][absence_type] += days
            stats["by_user"][user_id]["username"] = username

            # By status
            stats["by_status"][status] += 1

            # By month
            if date and breakdown_by_month:
                if hasattr(date, 'strftime'):
                    month_key = date.strftime("%Y-%m")
                else:
                    # Parse string date
                    try:
                        parsed_date = datetime.fromisoformat(str(date).replace('Z', '+00:00'))
                        month_key = parsed_date.strftime("%Y-%m")
                    except Exception:
                        month_key = "unknown"

                stats["by_month"][month_key]["count"] += 1
                stats["by_month"][month_key]["days"] += days
                stats["by_month"][month_key]["types"][absence_type] += days

        # Process sets and defaultdicts for JSON serialization
        stats["unique_users_count"] = len(stats["unique_users"])
        del stats["unique_users"]

        # Process by_type
        by_type_processed = {}
        for type_key, type_data in stats["by_type"].items():
            by_type_processed[type_key] = {
                "count": type_data["count"],
                "days": round(type_data["days"], 2),
                "unique_users": len(type_data["users"]),
                "label": AbsenceAnalytics.TYPE_LABELS.get(type_key, type_key)
            }
        stats["by_type"] = by_type_processed

        # Process by_user
        by_user_processed = {}
        for user_id, user_data in stats["by_user"].items():
            by_user_processed[str(user_id)] = {
                "username": user_data["username"],
                "count": user_data["count"],
                "days": round(user_data["days"], 2),
                "types": {k: round(v, 2) for k, v in dict(user_data["types"]).items()}
            }
        stats["by_user"] = by_user_processed

        # Process by_month
        if breakdown_by_month:
            by_month_processed = {}
            for month_key, month_data in sorted(stats["by_month"].items()):
                by_month_processed[month_key] = {
                    "count": month_data["count"],
                    "days": round(month_data["days"], 2),
                    "types": {k: round(v, 2) for k, v in dict(month_data["types"]).items()}
                }
            stats["by_month"] = by_month_processed
        else:
            del stats["by_month"]

        # Process by_status
        stats["by_status"] = dict(stats["by_status"])

        # Round totals
        stats["total_days"] = round(stats["total_days"], 2)

        # Calculate averages
        if stats["unique_users_count"] > 0:
            stats["avg_days_per_user"] = round(
                stats["total_days"] / stats["unique_users_count"], 2
            )

        # Top contributors (most absence days)
        sorted_users = sorted(
            stats["by_user"].items(),
            key=lambda x: x[1]["days"],
            reverse=True
        )
        stats["top_users"] = [
            {"user_id": uid, **udata}
            for uid, udata in sorted_users[:5]
        ]

        return stats

    @staticmethod
    def format_statistics_report(
        stats: Dict[str, Any],
        title: str = "Absence Statistics Report"
    ) -> str:
        """Format statistics into a readable report.

        Args:
            stats: Statistics dictionary from calculate_statistics
            title: Report title

        Returns:
            Formatted report string
        """
        if stats.get("total_entries", 0) == 0:
            return stats.get("message", "No data available for analysis")

        report = f"""# {title}

## Overview
- **Total Absences**: {stats['total_entries']} entries
- **Total Days**: {stats['total_days']} days
- **Unique Users**: {stats['unique_users_count']}
- **Average per User**: {stats.get('avg_days_per_user', 0)} days

## By Type
"""
        # Sort by days descending
        sorted_types = sorted(
            stats.get('by_type', {}).items(),
            key=lambda x: x[1]['days'],
            reverse=True
        )

        total_days = stats['total_days'] or 1
        for type_key, type_data in sorted_types:
            percentage = (type_data['days'] / total_days) * 100
            report += f"- **{type_data['label']}**: {type_data['days']} days ({percentage:.1f}%) - {type_data['count']} entries, {type_data['unique_users']} users\n"

        # By Status
        if stats.get('by_status'):
            report += "\n## By Status\n"
            for status, count in stats['by_status'].items():
                report += f"- {status}: {count} entries\n"

        # Top Users
        if stats.get('top_users'):
            report += "\n## Top Users (by absence days)\n"
            for i, user in enumerate(stats['top_users'], 1):
                report += f"{i}. **{user['username']}**: {user['days']} days ({user['count']} entries)\n"

                # Show type breakdown for top 3
                if i <= 3 and user.get('types'):
                    for type_key, days in sorted(user['types'].items(), key=lambda x: x[1], reverse=True):
                        type_label = AbsenceAnalytics.TYPE_LABELS.get(type_key, type_key)
                        report += f"   - {type_label}: {days} days\n"

        # Monthly breakdown if available
        if stats.get('by_month'):
            report += "\n## Monthly Trend\n"
            for month, month_data in stats['by_month'].items():
                report += f"- **{month}**: {month_data['days']} days ({month_data['count']} entries)\n"

        return report

    @staticmethod
    def calculate_sickness_stats(absences: List[Any]) -> Dict[str, Any]:
        """Calculate statistics specifically for sickness absences.

        Args:
            absences: List of absence entities

        Returns:
            Sickness-specific statistics
        """
        sickness_types = ['sickness', 'sickness_child']
        sickness_absences = [
            a for a in absences
            if getattr(a, 'type', '') in sickness_types
        ]

        stats = AbsenceAnalytics.calculate_statistics(
            sickness_absences,
            breakdown_by_month=True
        )

        # Add sickness-specific metrics
        if stats.get('total_entries', 0) > 0:
            stats["sickness_rate"] = round(
                stats['total_days'] / max(stats['unique_users_count'], 1), 2
            )
            stats["report_title"] = "Sickness Report"

        return stats
