"""API-only process entrypoint for Railway's assigned PORT."""
import os
import uvicorn

if __name__ == '__main__':
    uvicorn.run('backend.app.main:app', host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))
