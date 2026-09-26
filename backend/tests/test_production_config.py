import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings


def test_production_database_is_required():
    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="production", DATABASE_URL=None)


def test_production_database_configuration_is_allowed():
    settings = Settings(ENVIRONMENT="production", DATABASE_URL="postgresql+asyncpg://localhost/db")
    assert settings.DATABASE_URL


@pytest.mark.parametrize("environment", ["test", "development"])
def test_local_environments_allow_missing_database(environment):
    settings = Settings(ENVIRONMENT=environment, DATABASE_URL=None)
    assert settings.DATABASE_URL is None


def test_supabase_project_url_strips_rest_suffix():
    settings = Settings(SUPABASE_URL="https://example.supabase.co/rest/v1/")
    assert settings.SUPABASE_URL == "https://example.supabase.co"
