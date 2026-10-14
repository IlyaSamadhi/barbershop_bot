"""
Расчёт расписания: какие даты и какие часы показывать клиенту.

Здесь нет ничего про Telegram, только логика. Поэтому этот файл
легко проверять отдельно (см. test_logic.py).
"""

from datetime import date, datetime, timedelta

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]


def available_dates(today: date, days_ahead: int, days_off: list[int]) -> list[date]:
    """Даты, на которые можно записаться: от сегодня на days_ahead дней, без выходных."""
    result = []
    for i in range(days_ahead):
        d = today + timedelta(days=i)
        if d.weekday() not in days_off:
            result.append(d)
    return result


def all_slots(start_hour: int, end_hour: int) -> list[str]:
    """Все времена рабочего дня: ['10:00', '11:00', ..., '20:00']."""
    return [f"{h:02d}:00" for h in range(start_hour, end_hour + 1)]


def free_slots(day: date, now: datetime, booked: set[str],
               start_hour: int, end_hour: int) -> list[str]:
    """
    Свободные времена на день:
    — убираем уже занятые;
    — если день сегодняшний, убираем время, которое уже прошло.
    """
    result = []
    for slot in all_slots(start_hour, end_hour):
        if slot in booked:
            continue
        hour = int(slot[:2])
        if day == now.date() and hour <= now.hour:
            continue
        result.append(slot)
    return result


def format_date(d: date) -> str:
    """2026-10-15 -> 'Чт, 15 октября'."""
    return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"


def normalize_phone(text: str) -> str | None:
    """
    Проверяет телефон и приводит к виду +7XXXXXXXXXX.
    Принимает: 89001234567, +7 900 123-45-67, 9001234567 и т.п.
    Возвращает None, если это не похоже на российский номер.
    """
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    return None
