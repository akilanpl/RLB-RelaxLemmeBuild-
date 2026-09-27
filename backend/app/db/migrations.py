"""Database migration and schema management utilities."""

from pathlib import Path
from typing import Dict, Any
from sqlalchemy import text
from backend.app.db.session import get_engine


def get_schema_sql_path() -> Path:
    """Return the absolute path to the authoritative schema/supabase_schema.sql."""
    # Based on project-root/schema/supabase_schema.sql
    current_file = Path(__file__).resolve()
    # current_file is at backend/app/db/migrations.py
    project_root = current_file.parents[3]
    return project_root / "schema" / "supabase_schema.sql"


async def apply_schema() -> Dict[str, Any]:
    """
    Executes the frozen schema DDL against the configured database.
    Used for local test setup and deployment automation.
    """
    engine = get_engine()
    if engine is None:
        return {"status": "error", "message": "Database not configured."}

    schema_path = get_schema_sql_path()
    if not schema_path.exists():
        return {"status": "error", "message": f"Schema file not found at {schema_path}"}

    sql_content = schema_path.read_text(encoding="utf-8")

    async with engine.begin() as conn:
        # Execute DDL
        raw = (await conn.get_raw_connection()).driver_connection
        await raw.execute(sql_content)

    return {"status": "success", "message": "Schema successfully applied."}
