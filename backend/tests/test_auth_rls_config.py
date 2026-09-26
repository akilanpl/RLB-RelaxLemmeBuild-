"""Verification of Phase 2 Auth & RLS configuration and schema contracts."""

from pathlib import Path
from backend.app.core.config import Settings


def test_schema_sql_contains_auth_trigger_and_rls():
    """Verify that schema/supabase_schema.sql establishes strict user and workspace RLS."""
    schema_file = Path(__file__).resolve().parents[2] / "schema" / "supabase_schema.sql"
    assert schema_file.exists(), f"Schema file missing at {schema_file}"
    sql_text = schema_file.read_text(encoding="utf-8")

    # 1. Verify exact entities exist
    assert "CREATE TABLE users" in sql_text
    assert "CREATE TABLE workspaces" in sql_text
    assert "profiles" not in sql_text, "An extra profiles table must NOT be introduced; users is the 27-entity projection"

    # 2. Verify RLS is enabled
    assert "ALTER TABLE users ENABLE ROW LEVEL SECURITY;" in sql_text
    assert "ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;" in sql_text

    # 3. Verify granular user ownership policies (not broad 'all authenticated')
    assert "CREATE POLICY users_select_self ON users" in sql_text
    assert "auth.uid()" in sql_text
    assert "CREATE POLICY workspaces_select_owner ON workspaces" in sql_text
    assert "FOR SELECT USING (user_id = auth.uid())" in sql_text

    # 4. Verify auth identity projection trigger
    assert "handle_new_user" in sql_text
    assert "TRIGGER on_auth_user_created" in sql_text


def test_auth_configuration_status():
    """Sensitive Supabase keys must not have hardcoded Settings defaults."""
    assert Settings.model_fields["SUPABASE_SERVICE_ROLE_KEY"].default is None
    assert Settings.model_fields["SUPABASE_ANON_KEY"].default is None
