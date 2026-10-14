"""
Работа с базой данных SQLite.

SQLite — это база данных в одном файле (bookings.db). Ничего отдельно
устанавливать не нужно: она встроена в Python.
"""

import sqlite3
from contextlib import closing


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # строки можно читать по имени: row["name"]
    return conn


def init_db(db_path: str) -> None:
    """Создаёт таблицу записей, если её ещё нет."""
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                name        TEXT    NOT NULL,
                phone       TEXT    NOT NULL,
                service     TEXT    NOT NULL,
                price       INTEGER,            -- цена на момент записи, в рублях
                date        TEXT    NOT NULL,   -- формат ГГГГ-ММ-ДД
                time        TEXT    NOT NULL,   -- формат ЧЧ:ММ
                created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE (date, time)             -- одно время нельзя занять дважды
            )
            """
        )
        # Если база создана старой версией бота, в ней нет колонки price — добавляем.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(bookings)")}
        if "price" not in columns:
            conn.execute("ALTER TABLE bookings ADD COLUMN price INTEGER")


def get_booked_times(db_path: str, date: str) -> set[str]:
    """Возвращает множество занятых времён на дату, например {'10:00', '14:00'}."""
    with closing(_connect(db_path)) as conn:
        rows = conn.execute("SELECT time FROM bookings WHERE date = ?", (date,)).fetchall()
    return {row["time"] for row in rows}


def add_booking(db_path: str, user_id: int, name: str, phone: str,
                service: str, price: int, date: str, time: str) -> int | None:
    """
    Сохраняет запись вместе с ценой на момент записи. Возвращает её номер (id).
    Если это время уже успел занять кто-то другой, возвращает None.
    """
    try:
        with closing(_connect(db_path)) as conn, conn:
            cur = conn.execute(
                "INSERT INTO bookings (user_id, name, phone, service, price, date, time) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, name, phone, service, price, date, time),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_user_bookings(db_path: str, user_id: int, from_date: str) -> list[sqlite3.Row]:
    """Будущие записи конкретного клиента."""
    with closing(_connect(db_path)) as conn:
        return conn.execute(
            "SELECT * FROM bookings WHERE user_id = ? AND date >= ? ORDER BY date, time",
            (user_id, from_date),
        ).fetchall()


def get_all_bookings(db_path: str, from_date: str) -> list[sqlite3.Row]:
    """Все будущие записи (для владельца)."""
    with closing(_connect(db_path)) as conn:
        return conn.execute(
            "SELECT * FROM bookings WHERE date >= ? ORDER BY date, time",
            (from_date,),
        ).fetchall()


def get_booking(db_path: str, booking_id: int) -> sqlite3.Row | None:
    with closing(_connect(db_path)) as conn:
        return conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()


def cancel_booking(db_path: str, booking_id: int, user_id: int | None = None) -> bool:
    """
    Удаляет запись. Если передан user_id, клиент может отменить только свою запись.
    Возвращает True, если запись была удалена.
    """
    with closing(_connect(db_path)) as conn, conn:
        if user_id is None:
            cur = conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        else:
            cur = conn.execute(
                "DELETE FROM bookings WHERE id = ? AND user_id = ?", (booking_id, user_id)
            )
        return cur.rowcount > 0
