"""
Database connection management
"""
import psycopg2
from scripts.config import DATABASE_URL


def get_connection():
    """Get a raw PostgreSQL connection with UTF-8 encoding."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.set_client_encoding('UTF8')
    return conn
