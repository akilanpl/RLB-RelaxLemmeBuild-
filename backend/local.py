"""Offline-safe local API launcher. Existing project-root secrets are not loaded.

Create backend/.env.local with staging-only credentials when integration is needed.
"""
import os
from pathlib import Path
from dotenv import dotenv_values


def configure_local_environment(values, setting_names, data_dir=None):
    runtime_settings = {
        name: os.environ[name]
        for name in ("RLB_CONTROL_PLANE_URL", "RLB_DEVICE_TOKEN", "RLB_DESKTOP_ORIGIN", "CREDENTIAL_ENCRYPTION_KEY", "RLB_LOCAL_OWNER_ID")
        if name in os.environ
    }
    for name in setting_names:
        os.environ.pop(name, None)
    for name, value in values.items():
        if value is not None:
            os.environ[name] = value
    os.environ.update(runtime_settings)
    os.environ["ENVIRONMENT"] = "desktop" if os.environ.get("RLB_LOCAL_API_TOKEN") else "development"
    if os.environ["ENVIRONMENT"] == "desktop":
        os.environ["DEBUG"] = "false"
        os.environ["RUN_EMBEDDED_WORKER"] = "true"
        os.environ["DATABASE_URL"] = ""
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
    if data_dir:
        os.environ["LOCAL_DATA_DIR"] = data_dir


if __name__ == '__main__':
    from backend.app.core.config import Settings
    root = Path(__file__).resolve().parent
    configured = Path(os.environ['RLB_ENV_FILE']) if os.environ.get('RLB_ENV_FILE') else None
    source = configured if configured and configured.is_file() else root / '.env.local'
    if not source.is_file():
        source = root / '.env.example'
    values = dotenv_values(source)
    data_dir = os.environ.get('RLB_DATA_DIR')
    # Drop inherited cloud configuration but retain explicit desktop enrollment.
    configure_local_environment(values, Settings.model_fields, data_dir)
    Settings.model_config['env_file'] = str(source)
    import uvicorn
    uvicorn.run('backend.app.main:app', host='127.0.0.1', port=int(os.environ.get('PORT', '8000')))
