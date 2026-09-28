"""Validate configuration without printing values or contacting cloud services."""
from urllib.parse import urlparse
from backend.app.core.config import get_settings


def missing_configuration(role='api', settings=None):
    settings = settings or get_settings()
    if settings.ENVIRONMENT not in {'staging', 'production'}:
        return []
    required = ['DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'CREDENTIAL_ENCRYPTION_KEY']
    if role == 'worker':
        required += ['DAYTONA_API_KEY', 'DAYTONA_SANDBOX_IMAGE']
    return [name for name in required if not getattr(settings, name, None)]


def validate_hosted_configuration(role='api'):
    settings = get_settings()
    missing = missing_configuration(role, settings)
    if missing:
        raise RuntimeError('Missing hosted configuration: ' + ', '.join(missing))
    if settings.ENVIRONMENT in {'staging', 'production'}:
        from backend.app.services.credential_service import CredentialService
        CredentialService(settings.CREDENTIAL_ENCRYPTION_KEY)
        if settings.RUN_EMBEDDED_WORKER:
            raise RuntimeError('Hosted API and worker must run as separate processes.')
        if not settings.BACKEND_CORS_ORIGINS or '*' in settings.BACKEND_CORS_ORIGINS:
            raise RuntimeError('Hosted CORS must contain explicit allowed origins.')
        parsed = urlparse(settings.DATABASE_URL)
        if parsed.port == 6543:
            raise RuntimeError('Supabase Queue workers require a direct or session-pooler DATABASE_URL (port 5432), not transaction pooling.')
        if settings.DEBUG:
            raise RuntimeError('DEBUG must be false in hosted environments.')
        if settings.SUPABASE_QUEUE_NAME != 'task_execution':
            raise RuntimeError('SUPABASE_QUEUE_NAME must match the task_execution database trigger.')
