from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg2

DAG_ID = "youtube_product_sync_pipeline"
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/techdb"


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def check_env() -> bool:
    ok = True

    database_url = os.getenv("DATABASE_URL")
    youtube_api_key = os.getenv("YOUTUBE_API_KEY")

    if database_url:
        _ok("DATABASE_URL is set")
    else:
        _warn(f"DATABASE_URL is not set. Default will be used: {DEFAULT_DATABASE_URL}")

    if youtube_api_key:
        _ok("YOUTUBE_API_KEY is set")
    else:
        _warn("YOUTUBE_API_KEY is missing. DAG will fail on API calls.")
        ok = False

    return ok


def check_airflow_import_and_dag_parse() -> bool:
    try:
        from airflow.models import DagBag  # type: ignore
    except Exception as exc:
        _fail(f"Airflow import failed: {exc}")
        return False

    project_root = Path(__file__).resolve().parent
    dag_folder = project_root / "dags"
    if not dag_folder.exists():
        _fail("dags directory not found")
        return False

    dag_bag = DagBag(dag_folder=str(dag_folder), include_examples=False)

    if dag_bag.import_errors:
        _fail("DAG import errors found:")
        for dag_file, err in dag_bag.import_errors.items():
            print(f"  - {dag_file}: {err}")
        return False

    dag = dag_bag.get_dag(DAG_ID)
    if dag is None:
        _fail(f"DAG not found: {DAG_ID}")
        return False

    _ok(f"DAG parsed successfully: {DAG_ID}")
    _ok(f"Task count: {len(dag.tasks)}")
    return True


def check_database() -> bool:
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    try:
        with psycopg2.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name IN ('tech_products', 'videos', 'comments', 'comment_sentiments')
                    ORDER BY table_name
                    """
                )
                tables = {row[0] for row in cur.fetchall()}

        _ok("Database connection successful")

        required = {"tech_products", "videos", "comments", "comment_sentiments"}
        missing = required - tables
        if missing:
            _warn(f"Missing tables (DAG can create them on first run): {sorted(missing)}")
        else:
            _ok("All required tables already exist")

        return True
    except Exception as exc:
        _fail(f"Database check failed: {exc}")
        return False


def main() -> int:
    print("=== Airflow Pipeline Verification ===")
    env_ok = check_env()
    airflow_ok = check_airflow_import_and_dag_parse()
    db_ok = check_database()

    all_ok = env_ok and airflow_ok and db_ok

    print("\n=== Summary ===")
    print(f"Environment check: {'PASS' if env_ok else 'FAIL'}")
    print(f"Airflow DAG parse: {'PASS' if airflow_ok else 'FAIL'}")
    print(f"Database check: {'PASS' if db_ok else 'FAIL'}")

    if all_ok:
        _ok("Airflow pipeline is ready")
        return 0

    _warn("Some checks failed. See logs above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
