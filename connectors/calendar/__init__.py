"""Calendar connector: Google Calendar API / ICS / fixture → PullRecord[]."""

from connectors.calendar.adapter import CalendarConfigError, CalendarConnector

__all__ = ["CalendarConnector", "CalendarConfigError"]
