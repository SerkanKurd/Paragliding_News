import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
import difflib


from contextlib import contextmanager


DEFAULT_DB_PATH = "news.db"


@contextmanager
def get_db(db_path: str = DEFAULT_DB_PATH):
    """Context manager for SQLite connection that guarantees commit and close."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH):
    """Initializes SQLite database and tables."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT UNIQUE NOT NULL,
                published TEXT,
                raw_content TEXT,
                category TEXT,
                summary_en TEXT,
                pilot_takeaway_en TEXT,
                title_tr TEXT,
                summary_tr TEXT,
                pilot_takeaway_tr TEXT,
                status TEXT DEFAULT 'pending',  -- 'pending', 'analyzed', 'translated', 'failed'
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_link ON articles(link)")
        conn.commit()


def normalize_title(title: str) -> str:
    """Simple normalization for title duplicate comparisons."""
    if not title:
        return ""
    import re
    cleaned = re.sub(r'[^\w\s]', '', title.lower())
    return " ".join(cleaned.split())


def is_title_similar(t1: str, t2: str, threshold: float = 0.80) -> bool:
    """Checks if two titles are substantially identical."""
    n1, n2 = normalize_title(t1), normalize_title(t2)
    if not n1 or not n2:
        return False
    if n1 == n2 or n1 in n2 or n2 in n1:
        return True
    ratio = difflib.SequenceMatcher(None, n1, n2).ratio()
    return ratio >= threshold


def insert_or_deduplicate(
    source: str,
    title: str,
    link: str,
    published: str,
    db_path: str = DEFAULT_DB_PATH
) -> Optional[int]:
    """
    Inserts a newly discovered link.
    If duplicate is found (same link or very similar title):
      - Prioritizes keeping translated articles.
      - Discards/deletes the untranslated copy.
    """
    if not link or not title:
        return None

    with get_db(db_path) as conn:
        cursor = conn.cursor()

        # 1. Check exact link match
        cursor.execute("SELECT id, status, title_tr, summary_tr FROM articles WHERE link = ?", (link,))
        existing_by_link = cursor.fetchone()

        if existing_by_link:
            # If existing article is already translated, KEEP IT, do not overwrite with pending
            if existing_by_link["status"] == "translated" or existing_by_link["title_tr"]:
                return None  # Skip duplicate, translated copy preserved

            # If existing is NOT translated, update published/title if needed
            cursor.execute("""
                UPDATE articles
                SET title = ?, published = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status != 'translated'
            """, (title, published, existing_by_link["id"]))
            conn.commit()
            return existing_by_link["id"]

        # 2. Check title similarity with existing articles
        cursor.execute("SELECT id, title, status, title_tr, summary_tr FROM articles")
        all_articles = cursor.fetchall()

        for art in all_articles:
            if is_title_similar(title, art["title"]):
                # Duplicate title found!
                # Requirement: Prioritize deleting untranslated one
                if art["status"] == "translated" or art["title_tr"]:
                    # Existing is already translated, skip new untranslated one
                    return None
                else:
                    # Existing is untranslated. Replace or keep newer link
                    cursor.execute("""
                        UPDATE articles
                        SET link = ?, source = ?, published = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (link, source, published, art["id"]))
                    conn.commit()
                    return art["id"]

        # 3. Fresh unique article: insert as pending
        cursor.execute("""
            INSERT INTO articles (source, title, link, published, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (source, title, link, published))
        conn.commit()
        return cursor.lastrowid


def clean_database_duplicates(db_path: str = DEFAULT_DB_PATH) -> int:
    """
    Scans entire database for duplicate entries.
    Prioritizes keeping translated articles; deletes untranslated duplicates.
    """
    deleted_count = 0
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, link, status, title_tr, summary_tr FROM articles ORDER BY id ASC")
        articles = [dict(r) for r in cursor.fetchall()]

        to_delete = set()
        for i in range(len(articles)):
            if articles[i]["id"] in to_delete:
                continue
            for j in range(i + 1, len(articles)):
                if articles[j]["id"] in to_delete:
                    continue

                is_dup = (articles[i]["link"] == articles[j]["link"]) or is_title_similar(articles[i]["title"], articles[j]["title"])
                if is_dup:
                    a1 = articles[i]
                    a2 = articles[j]
                    a1_is_tr = (a1["status"] == "translated" or bool(a1["title_tr"]))
                    a2_is_tr = (a2["status"] == "translated" or bool(a2["title_tr"]))

                    # Rule: Prioritize keeping translated, delete untranslated
                    if a1_is_tr and not a2_is_tr:
                        to_delete.add(a2["id"])
                    elif a2_is_tr and not a1_is_tr:
                        to_delete.add(a1["id"])
                        break  # a1 is marked for deletion, stop comparing it
                    else:
                        # Neither or both translated: keep the earlier one, delete the other
                        to_delete.add(a2["id"])

        for del_id in to_delete:
            cursor.execute("DELETE FROM articles WHERE id = ?", (del_id,))
            deleted_count += 1

        conn.commit()
    return deleted_count


def get_pending_articles(limit: int = 10, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retrieves articles waiting for content fetch and analysis."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, source, title, link, published, raw_content
            FROM articles
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cursor.fetchall()]


def update_analyzed_article(
    article_id: int,
    raw_content: str,
    category: str,
    summary_en: str,
    pilot_takeaway_en: str,
    db_path: str = DEFAULT_DB_PATH
):
    """Saves Model 2 analysis output and marks article as 'analyzed'."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE articles
            SET raw_content = ?,
                category = ?,
                summary_en = ?,
                pilot_takeaway_en = ?,
                status = 'analyzed',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (raw_content, category, summary_en, pilot_takeaway_en, article_id))
        conn.commit()


def get_untranslated_articles(limit: int = 10, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retrieves analyzed articles waiting for Turkish aviation translation."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, source, title, link, published, category, summary_en, pilot_takeaway_en
            FROM articles
            WHERE status = 'analyzed'
            ORDER BY id ASC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cursor.fetchall()]


def update_translated_article(
    article_id: int,
    title_tr: str,
    summary_tr: str,
    pilot_takeaway_tr: str,
    db_path: str = DEFAULT_DB_PATH
):
    """Saves Model 3 Turkish translation and marks article as 'translated'."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE articles
            SET title_tr = ?,
                summary_tr = ?,
                pilot_takeaway_tr = ?,
                status = 'translated',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (title_tr, summary_tr, pilot_takeaway_tr, article_id))
        conn.commit()


def mark_article_failed(article_id: int, error_message: str, db_path: str = DEFAULT_DB_PATH):
    """Marks article as failed with an error message."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE articles
            SET status = 'failed',
                error_message = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (error_message, article_id))
        conn.commit()


def get_latest_translated_articles(limit: int = 30, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Fetches translated articles to compile the final digest."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, source, title, title_tr, link, published, category,
                   summary_en, summary_tr, pilot_takeaway_en, pilot_takeaway_tr
            FROM articles
            WHERE status = 'translated'
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cursor.fetchall()]


def get_stats(db_path: str = DEFAULT_DB_PATH) -> Dict[str, int]:
    """Returns status counts from articles table."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) as count FROM articles GROUP BY status")
        counts = {r["status"]: r["count"] for r in cursor.fetchall()}
        cursor.execute("SELECT COUNT(*) FROM articles")
        counts["total"] = cursor.fetchone()[0]
        return counts
