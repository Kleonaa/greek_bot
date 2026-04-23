import os
import sqlite3
from datetime import date

DB_PATH = os.getenv("DB_PATH", "greek.db")
WORDS_FILE = "words.txt"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY,
            greek TEXT NOT NULL,
            translation TEXT NOT NULL,
            example_gr TEXT,
            example_ru TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER NOT NULL,
            word_id INTEGER NOT NULL,
            ease_factor REAL DEFAULT 2.5,
            interval INTEGER DEFAULT 0,
            repetitions INTEGER DEFAULT 0,
            next_review TEXT DEFAULT '2000-01-01',
            PRIMARY KEY (user_id, word_id)
        )
    """)
    conn.commit()
    conn.close()


def load_words():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM words")
    if c.fetchone()[0] > 0:
        conn.close()
        return
    with open(WORDS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "–" not in line:
                continue
            parts = line.split("–", 1)
            greek = parts[0].strip()
            translation = parts[1].strip()
            if greek and translation:
                c.execute(
                    "INSERT INTO words (greek, translation) VALUES (?, ?)",
                    (greek, translation),
                )
    conn.commit()
    count = c.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    conn.close()
    print(f"Loaded {count} words into database.")


def get_session_words(user_id: int, max_reviews: int = 30, max_new: int = 15):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        SELECT w.id, w.greek, w.translation, w.example_gr, w.example_ru,
               p.ease_factor, p.interval, p.repetitions
        FROM words w
        JOIN progress p ON p.word_id = w.id AND p.user_id = ?
        WHERE p.next_review <= ?
        ORDER BY p.next_review ASC
        LIMIT ?
        """,
        (user_id, today, max_reviews),
    )
    reviews = c.fetchall()

    c.execute(
        """
        SELECT w.id, w.greek, w.translation, w.example_gr, w.example_ru,
               2.5, 0, 0
        FROM words w
        LEFT JOIN progress p ON p.word_id = w.id AND p.user_id = ?
        WHERE p.word_id IS NULL
        ORDER BY w.id
        LIMIT ?
        """,
        (user_id, max_new),
    )
    new_words = c.fetchall()
    conn.close()
    return list(reviews) + list(new_words)


def update_progress(
    user_id: int,
    word_id: int,
    ease_factor: float,
    interval: int,
    repetitions: int,
    next_review: str,
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO progress (user_id, word_id, ease_factor, interval, repetitions, next_review)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, word_id) DO UPDATE SET
            ease_factor = excluded.ease_factor,
            interval    = excluded.interval,
            repetitions = excluded.repetitions,
            next_review = excluded.next_review
        """,
        (user_id, word_id, ease_factor, interval, repetitions, next_review),
    )
    conn.commit()
    conn.close()


def save_example(word_id: int, example_gr: str, example_ru: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE words SET example_gr = ?, example_ru = ? WHERE id = ?",
        (example_gr, example_ru, word_id),
    )
    conn.commit()
    conn.close()


def get_stats(user_id: int) -> dict:
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    seen = c.execute(
        "SELECT COUNT(*) FROM progress WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    known = c.execute(
        "SELECT COUNT(*) FROM progress WHERE user_id = ? AND interval >= 21",
        (user_id,),
    ).fetchone()[0]
    due = c.execute(
        "SELECT COUNT(*) FROM progress WHERE user_id = ? AND next_review <= ?",
        (user_id, today),
    ).fetchone()[0]
    conn.close()
    return {"total": total, "seen": seen, "known": known, "due": due}
