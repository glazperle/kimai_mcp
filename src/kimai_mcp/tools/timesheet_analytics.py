"""Analytics extension for timesheet calculations."""

from typing import Dict, List, Any
from collections import defaultdict


class TimesheetAnalytics:
    """Performs calculations on timesheet data."""
    
    @staticmethod
    def calculate_statistics(timesheets: List[Any], include_details: bool = False, breakdown_by_year: bool = False) -> Dict[str, Any]:
        """Calculate comprehensive statistics from timesheet data."""
        if not timesheets:
            return {
                "total_entries": 0,
                "total_hours": 0,
                "message": "No timesheets found for analysis"
            }

        stats = {
            "total_entries": len(timesheets),
            "total_hours": 0.0,
            "billable_hours": 0.0,
            "non_billable_hours": 0.0,
            "running_timers": 0,
            "completed_entries": 0,
            "working_days": set(),
            "projects": defaultdict(float),
            "activities": defaultdict(float),
            "daily_hours": defaultdict(float),
            "weekly_hours": defaultdict(float),
            "monthly_hours": defaultdict(float),
            "yearly_hours": defaultdict(float),  # New: yearly breakdown
            "hourly_distribution": defaultdict(int),
            "tags": defaultdict(int),
            "breakdown_by_year": breakdown_by_year
        }
        
        # If breakdown by year is requested, track per-year stats
        if breakdown_by_year:
            stats["years"] = defaultdict(lambda: {
                "entries": 0,
                "total_hours": 0.0,
                "billable_hours": 0.0,
                "non_billable_hours": 0.0,
                "working_days": set(),
                "projects": defaultdict(float),
                "monthly_hours": defaultdict(float)
            })

        for ts in timesheets:
            if not ts.end:
                stats["running_timers"] += 1
                continue
                
            stats["completed_entries"] += 1

            duration_hours = (ts.end - ts.begin).total_seconds() / 3600
            stats["total_hours"] += duration_hours

            if ts.billable:
                stats["billable_hours"] += duration_hours
            else:
                stats["non_billable_hours"] += duration_hours

            stats["working_days"].add(ts.begin.date())

            if ts.project:
                stats["projects"][ts.project] += duration_hours

            if ts.activity:
                stats["activities"][ts.activity] += duration_hours

            date_key = ts.begin.date().isoformat()
            stats["daily_hours"][date_key] += duration_hours

            year, week, _ = ts.begin.isocalendar()
            week_key = f"{year}-W{week:02d}"
            stats["weekly_hours"][week_key] += duration_hours

            month_key = ts.begin.strftime("%Y-%m")
            stats["monthly_hours"][month_key] += duration_hours

            year_key = ts.begin.year
            stats["yearly_hours"][year_key] += duration_hours
            
            # Per-year breakdown if requested
            if breakdown_by_year:
                year_stats = stats["years"][year_key]
                year_stats["entries"] += 1
                year_stats["total_hours"] += duration_hours
                year_stats["working_days"].add(ts.begin.date())
                
                if ts.billable:
                    year_stats["billable_hours"] += duration_hours
                else:
                    year_stats["non_billable_hours"] += duration_hours
                
                if ts.project:
                    year_stats["projects"][ts.project] += duration_hours
                
                year_month_key = ts.begin.strftime("%m")
                year_stats["monthly_hours"][year_month_key] += duration_hours

            stats["hourly_distribution"][ts.begin.hour] += 1

            if ts.tags:
                for tag in ts.tags:
                    stats["tags"][tag] += 1

        working_days_count = len(stats["working_days"])
        stats["working_days_count"] = working_days_count
        stats["avg_hours_per_day"] = (
            stats["total_hours"] / working_days_count 
            if working_days_count > 0 else 0
        )

        expected_hours = working_days_count * 8
        stats["overtime_hours"] = max(0, stats["total_hours"] - expected_hours)
        stats["expected_hours"] = expected_hours

        stats["projects"] = dict(stats["projects"])
        stats["activities"] = dict(stats["activities"])
        stats["daily_hours"] = dict(stats["daily_hours"])
        stats["weekly_hours"] = dict(stats["weekly_hours"])
        stats["monthly_hours"] = dict(stats["monthly_hours"])
        stats["yearly_hours"] = dict(stats["yearly_hours"])
        stats["hourly_distribution"] = dict(stats["hourly_distribution"])
        stats["tags"] = dict(stats["tags"])
        
        # Process per-year stats if breakdown was requested
        if breakdown_by_year and stats["years"]:
            processed_years = {}
            for year, year_data in stats["years"].items():
                processed_years[str(year)] = {
                    "entries": year_data["entries"],
                    "total_hours": round(year_data["total_hours"], 2),
                    "billable_hours": round(year_data["billable_hours"], 2),
                    "non_billable_hours": round(year_data["non_billable_hours"], 2),
                    "working_days_count": len(year_data["working_days"]),
                    "avg_hours_per_day": round(
                        year_data["total_hours"] / len(year_data["working_days"]) 
                        if year_data["working_days"] else 0, 2
                    ),
                    "projects": dict(year_data["projects"]),
                    "monthly_hours": dict(year_data["monthly_hours"])
                }
            stats["years"] = processed_years

        del stats["working_days"]
        
        # Add summary percentages
        if stats["total_hours"] > 0:
            stats["billable_percentage"] = round(
                (stats["billable_hours"] / stats["total_hours"]) * 100, 1
            )
            
            # Top projects by percentage
            stats["top_projects"] = [
                {
                    "project_id": proj_id,
                    "hours": round(hours, 2),
                    "percentage": round((hours / stats["total_hours"]) * 100, 1)
                }
                for proj_id, hours in sorted(
                    stats["projects"].items(), 
                    key=lambda x: x[1], 
                    reverse=True
                )[:5]
            ]
        
        # Find peak productivity hours
        if stats["hourly_distribution"]:
            peak_hour = max(stats["hourly_distribution"].items(), key=lambda x: x[1])
            stats["peak_hour"] = {
                "hour": peak_hour[0],
                "entries": peak_hour[1]
            }

        stats["total_hours"] = round(stats["total_hours"], 2)
        stats["billable_hours"] = round(stats["billable_hours"], 2)
        stats["non_billable_hours"] = round(stats["non_billable_hours"], 2)
        stats["avg_hours_per_day"] = round(stats["avg_hours_per_day"], 2)
        stats["overtime_hours"] = round(stats["overtime_hours"], 2)
        
        return stats

    @staticmethod
    def format_statistics_report(stats: Dict[str, Any], project_map: Dict[int, str] = None) -> str:
        """Format statistics into a readable report."""
        if stats.get("total_entries", 0) == 0:
            return stats.get("message", "No data available for analysis")
        
        report = f"""# Timesheet Analytics Report

## Overview
- **Total Entries**: {stats['total_entries']} ({stats['completed_entries']} completed, {stats['running_timers']} running)
- **Total Hours**: {stats['total_hours']} hours
- **Working Days**: {stats['working_days_count']} days
- **Average Hours/Day**: {stats['avg_hours_per_day']} hours

## Time Distribution
- **Billable Hours**: {stats['billable_hours']} ({stats.get('billable_percentage', 0)}%)
- **Non-Billable Hours**: {stats['non_billable_hours']} hours
- **Expected Hours** (8h/day): {stats['expected_hours']} hours
- **Overtime**: {stats['overtime_hours']} hours

## Top Projects
"""
        for proj in stats.get('top_projects', [])[:5]:
            if project_map and proj['project_id'] in project_map:
                project_name = project_map[proj['project_id']]
                report += f"- {project_name}: {proj['hours']}h ({proj['percentage']}%)\n"
            else:
                report += f"- Project {proj['project_id']}: {proj['hours']}h ({proj['percentage']}%)\n"
        
        if stats.get('peak_hour'):
            report += "\n## Peak Productivity\n"
            report += f"- Most entries start at: {stats['peak_hour']['hour']}:00 ({stats['peak_hour']['entries']} entries)\n"
        
        # Add yearly breakdown if available
        if stats.get('breakdown_by_year') and stats.get('years'):
            report += "\n## Yearly Breakdown\n"
            
            years_sorted = sorted(stats['years'].items())
            for year, year_data in years_sorted:
                report += f"\n### Year {year}\n"
                report += f"- **Hours**: {year_data['total_hours']}h ({year_data['entries']} entries)\n"
                report += f"- **Working Days**: {year_data['working_days_count']} days\n"
                report += f"- **Average/Day**: {year_data['avg_hours_per_day']}h\n"
                report += f"- **Billable**: {year_data['billable_hours']}h\n"
                
                # Top projects for this year
                if year_data['projects']:
                    top_project = max(year_data['projects'].items(), key=lambda x: x[1])
                    if project_map and top_project[0] in project_map:
                        project_name = project_map[top_project[0]]
                    else:
                        project_name = f"Project {top_project[0]}"
                    report += f"- **Main Project**: {project_name} ({round(top_project[1], 2)}h)\n"
            
            # Year comparison if multiple years
            if len(years_sorted) > 1:
                report += "\n### Year-over-Year Comparison\n"
                for i in range(1, len(years_sorted)):
                    prev_year, prev_data = years_sorted[i-1]
                    curr_year, curr_data = years_sorted[i]
                    
                    hours_change = curr_data['total_hours'] - prev_data['total_hours']
                    hours_pct = (hours_change / prev_data['total_hours'] * 100) if prev_data['total_hours'] > 0 else 0
                    
                    days_change = curr_data['working_days_count'] - prev_data['working_days_count']
                    
                    report += f"- **{prev_year} → {curr_year}**: "
                    report += f"{hours_change:+.0f}h ({hours_pct:+.1f}%), "
                    report += f"{days_change:+d} working days\n"
        
        # Add weekly summary if available and no yearly breakdown
        elif stats.get('weekly_hours'):
            report += "\n## Recent Weekly Hours\n"
            recent_weeks = sorted(stats['weekly_hours'].items())[-4:]
            for week, hours in recent_weeks:
                report += f"- {week}: {round(hours, 2)} hours\n"
        
        return report