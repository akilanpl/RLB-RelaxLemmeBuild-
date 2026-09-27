"""Offline-safe local API launcher. Existing project-root secrets are not loaded.

Create backend/.env.local with staging-only credentials when integration is needed.
"""
import os
from pathlib import Path
from dotenv import dotenv_values

if __name__ == '__main__':
    from backend.app.core.config import Settings
    root = Path(__file__).resolve().parent
    source = root / '.env.local'
    values = dotenv_values(source if source.exists() else root / '.env.example')
    # Drop inherited cloud configuration before loading the explicit local file.
    for name in Settings.model_fields:
        os.environ.pop(name, None)
    for name, value in values.items():
        if value is not None:
            os.environ[name] = value
    os.environ['ENVIRONMENT'] = 'development'
    Settings.model_config['env_file'] = str(source) if source.exists() else str(root / '.env.example')
    import uvicorn
    uvicorn.run('backend.app.main:app', host='127.0.0.1', port=int(os.environ.get('PORT', '8000')))
