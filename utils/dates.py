from datetime import date, timedelta

WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def mask_to_text(mask: int) -> str:
    if mask == 127:
        return "каждый день"
    return ", ".join(name for i, name in enumerate(WEEKDAY_NAMES) if mask & (1 << i))


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def days_between(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
