"""
Database query helper functions
"""
from typing import Optional, List, Dict
from psycopg2.extras import RealDictCursor
from scripts.database.connection import get_connection


def query_one(sql: str, params: tuple = ()) -> Optional[Dict]:
    """Execute query and return single row as dict."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(sql, params)
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result


def query_all(sql: str, params: tuple = ()) -> List[Dict]:
    """Execute query and return all rows as dicts."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(sql, params)
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results


def execute_insert(sql: str, params: tuple = ()) -> int:
    """Execute INSERT and return inserted ID (for SERIAL columns)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    result_id = cursor.fetchone()[0] if cursor.description else None
    conn.commit()
    cursor.close()
    conn.close()
    return result_id


def execute_update(sql: str, params: tuple = ()) -> int:
    """Execute UPDATE/DELETE and return row count."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    row_count = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    return row_count
