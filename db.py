import csv
import os
import sqlite3
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "greek.db"))
WORDS_FILE = BASE_DIR / "words.txt"
RANKED_WORDS_FILE = BASE_DIR / "data" / "words_ranked.csv"
LEARNING_ORDER_FILE = BASE_DIR / "data" / "learning_order.csv"
VERB_FORMS_FILE = BASE_DIR / "data" / "verb_forms.csv"


def add_column_if_missing(cursor, table: str, existing_columns: set[str], column: str):
    column_name = column.split()[0]
    if column_name not in existing_columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        existing_columns.add(column_name)


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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
    c.execute("PRAGMA table_info(words)")
    columns = {row[1] for row in c.fetchall()}
    add_column_if_missing(c, "words", columns, "example_gr TEXT")
    add_column_if_missing(c, "words", columns, "example_ru TEXT")
    add_column_if_missing(c, "words", columns, "example_form TEXT")
    add_column_if_missing(c, "words", columns, "frequency_rank INTEGER")
    add_column_if_missing(c, "words", columns, "learning_order INTEGER")
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS verb_forms (
            id INTEGER PRIMARY KEY,
            present TEXT NOT NULL UNIQUE,
            future TEXT NOT NULL,
            past TEXT NOT NULL,
            translation TEXT NOT NULL,
            notes TEXT,
            learning_order INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS verb_progress (
            user_id INTEGER NOT NULL,
            verb_id INTEGER NOT NULL,
            ease_factor REAL DEFAULT 2.5,
            interval INTEGER DEFAULT 0,
            repetitions INTEGER DEFAULT 0,
            next_review TEXT DEFAULT '2000-01-01',
            PRIMARY KEY (user_id, verb_id)
        )
    """)
    conn.commit()
    conn.close()


def read_word_rows():
    ordered_words_file = (
        LEARNING_ORDER_FILE if LEARNING_ORDER_FILE.exists() else RANKED_WORDS_FILE
    )
    if ordered_words_file.exists():
        with ordered_words_file.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                greek = row["greek"].strip()
                translation = row["translation"].strip()
                frequency_rank = row["greeklex_rank"].strip()
                learning_order = row["learning_order"].strip()
                if greek and translation:
                    yield (
                        greek,
                        translation,
                        int(frequency_rank) if frequency_rank else None,
                        int(learning_order) if learning_order else None,
                    )
        return

    with WORDS_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "–" not in line:
                continue
            parts = line.split("–", 1)
            greek = parts[0].strip()
            translation = parts[1].strip()
            if greek and translation:
                yield greek, translation, None, None


def load_words():
    word_rows = list(read_word_rows())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM words")
    existing_count = c.fetchone()[0]

    if existing_count == 0:
        for greek, translation, frequency_rank, learning_order in word_rows:
            c.execute(
                """
                INSERT INTO words (greek, translation, frequency_rank, learning_order)
                VALUES (?, ?, ?, ?)
                """,
                (greek, translation, frequency_rank, learning_order),
            )
    else:
        for greek, translation, frequency_rank, learning_order in word_rows:
            c.execute(
                """
                UPDATE words
                SET translation = ?,
                    frequency_rank = ?,
                    learning_order = ?
                WHERE greek = ?
                """,
                (translation, frequency_rank, learning_order, greek),
            )
    conn.commit()
    count = c.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    conn.close()
    if existing_count == 0:
        print(f"Loaded {count} words into database.")
    else:
        print(f"Updated word ordering metadata for {count} words.")


def load_verb_forms():
    if not VERB_FORMS_FILE.exists():
        return

    with VERB_FORMS_FILE.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for row in rows:
        learning_order = row["learning_order"].strip()
        c.execute(
            """
            INSERT INTO verb_forms (
                present, future, past, translation, notes, learning_order
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(present) DO UPDATE SET
                future = excluded.future,
                past = excluded.past,
                translation = excluded.translation,
                notes = excluded.notes,
                learning_order = excluded.learning_order
            """,
            (
                row["present"].strip(),
                row["future"].strip(),
                row["past"].strip(),
                row["translation"].strip(),
                row["notes"].strip(),
                int(learning_order) if learning_order else None,
            ),
        )
    conn.commit()
    count = c.execute("SELECT COUNT(*) FROM verb_forms").fetchone()[0]
    conn.close()
    print(f"Loaded/updated {count} verb forms.")


def get_session_words(user_id: int, max_reviews: int = 30, max_new: int = 15):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        SELECT w.id, w.greek, w.translation, w.example_gr, w.example_ru, w.example_form,
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
        SELECT w.id, w.greek, w.translation, w.example_gr, w.example_ru, w.example_form,
               2.5, 0, 0
        FROM words w
        LEFT JOIN progress p ON p.word_id = w.id AND p.user_id = ?
        WHERE p.word_id IS NULL
        ORDER BY COALESCE(w.learning_order, w.frequency_rank, w.id)
        LIMIT ?
        """,
        (user_id, max_new),
    )
    new_words = c.fetchall()
    conn.close()
    return list(reviews) + list(new_words)


def get_verb_session(user_id: int, max_reviews: int = 15, max_new: int = 10):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        SELECT v.id, v.present, v.future, v.past, v.translation, v.notes,
               p.ease_factor, p.interval, p.repetitions
        FROM verb_forms v
        JOIN verb_progress p ON p.verb_id = v.id AND p.user_id = ?
        WHERE p.next_review <= ?
        ORDER BY p.next_review ASC
        LIMIT ?
        """,
        (user_id, today, max_reviews),
    )
    reviews = c.fetchall()

    c.execute(
        """
        SELECT v.id, v.present, v.future, v.past, v.translation, v.notes,
               2.5, 0, 0
        FROM verb_forms v
        LEFT JOIN verb_progress p ON p.verb_id = v.id AND p.user_id = ?
        WHERE p.verb_id IS NULL
        ORDER BY COALESCE(v.learning_order, v.id)
        LIMIT ?
        """,
        (user_id, max_new),
    )
    new_forms = c.fetchall()
    conn.close()
    return list(reviews) + list(new_forms)


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


def update_verb_progress(
    user_id: int,
    verb_id: int,
    ease_factor: float,
    interval: int,
    repetitions: int,
    next_review: str,
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO verb_progress (
            user_id, verb_id, ease_factor, interval, repetitions, next_review
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, verb_id) DO UPDATE SET
            ease_factor = excluded.ease_factor,
            interval    = excluded.interval,
            repetitions = excluded.repetitions,
            next_review = excluded.next_review
        """,
        (user_id, verb_id, ease_factor, interval, repetitions, next_review),
    )
    conn.commit()
    conn.close()


def save_example(word_id: int, example_gr: str, example_ru: str, example_form: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        UPDATE words
        SET example_gr = ?, example_ru = ?, example_form = ?
        WHERE id = ?
        """,
        (example_gr, example_ru, example_form, word_id),
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


def get_verb_stats(user_id: int) -> dict:
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM verb_forms").fetchone()[0]
    seen = c.execute(
        "SELECT COUNT(*) FROM verb_progress WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    known = c.execute(
        "SELECT COUNT(*) FROM verb_progress WHERE user_id = ? AND interval >= 21",
        (user_id,),
    ).fetchone()[0]
    due = c.execute(
        "SELECT COUNT(*) FROM verb_progress WHERE user_id = ? AND next_review <= ?",
        (user_id, today),
    ).fetchone()[0]
    conn.close()
    return {"total": total, "seen": seen, "known": known, "due": due}
