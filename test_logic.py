"""
Проверка логики бота без Telegram.

Запуск:  python test_logic.py
Если в конце написано «Все проверки пройдены», значит расписание и база работают правильно.
"""

import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import date, datetime

import db
from schedule import available_dates, format_date, free_slots, normalize_phone


def test_dates():
    monday = date(2026, 10, 12)
    dates = available_dates(monday, 7, days_off=[6])
    assert len(dates) == 6, "воскресенье должно быть выходным"
    assert all(d.weekday() != 6 for d in dates)
    assert format_date(date(2026, 10, 15)) == "Чт, 15 октября"


def test_slots():
    day = date(2026, 10, 15)
    # Другой день: все 11 часов с 10 до 20, минус занятые
    morning_before = datetime(2026, 10, 14, 9, 0)
    slots = free_slots(day, morning_before, {"12:00"}, 10, 20)
    assert slots[0] == "10:00" and slots[-1] == "20:00"
    assert "12:00" not in slots and len(slots) == 10
    # Сегодня в 14:30: прошедшие часы и текущий (14:00) не предлагаем
    now = datetime(2026, 10, 15, 14, 30)
    slots_today = free_slots(day, now, set(), 10, 20)
    assert slots_today[0] == "15:00"


def test_phone():
    assert normalize_phone("89001234567") == "+79001234567"
    assert normalize_phone("+7 (900) 123-45-67") == "+79001234567"
    assert normalize_phone("9001234567") == "+79001234567"
    assert normalize_phone("привет") is None
    assert normalize_phone("12345") is None


def test_db():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.db")
        db.init_db(path)
        first = db.add_booking(path, 1, "Илья", "+79001234567", "haircut", 1200, "2026-10-15", "10:00")
        assert first is not None
        # Цена сохранилась в записи и не зависит от config.py
        assert db.get_booking(path, first)["price"] == 1200
        # Второй клиент не может занять то же время
        second = db.add_booking(path, 2, "Пётр", "+79007654321", "beard", 800, "2026-10-15", "10:00")
        assert second is None
        assert db.get_booked_times(path, "2026-10-15") == {"10:00"}
        assert len(db.get_user_bookings(path, 1, "2026-10-01")) == 1
        # Чужую запись отменить нельзя, свою можно
        assert db.cancel_booking(path, first, user_id=2) is False
        assert db.cancel_booking(path, first, user_id=1) is True
        assert db.get_booked_times(path, "2026-10-15") == set()


def test_db_upgrade():
    # Старая база без колонки price должна обновиться сама, а записи сохраниться
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "old.db")
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute(
                "CREATE TABLE bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, "
                "service TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')), "
                "UNIQUE (date, time))"
            )
            conn.execute(
                "INSERT INTO bookings (user_id, name, phone, service, date, time) "
                "VALUES (1, 'Олег', '+79001234567', 'haircut', '2026-10-15', '19:00')"
            )
        db.init_db(path)
        old = db.get_all_bookings(path, "2026-10-01")[0]
        assert old["name"] == "Олег" and old["price"] is None


if __name__ == "__main__":
    test_dates()
    test_slots()
    test_phone()
    test_db()
    test_db_upgrade()
    print("Все проверки пройдены ✅")
