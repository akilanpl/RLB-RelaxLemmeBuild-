"""Print required configuration NAMES only. Does not read .env or contact services."""
import os
import sys

role = sys.argv[1] if len(sys.argv) > 1 else 'api'
required = {
    'frontend': ['NEXT_PUBLIC_API_URL', 'NEXT_PUBLIC_SUPABASE_URL', 'NEXT_PUBLIC_SUPABASE_ANON_KEY'],
    'api': ['ENVIRONMENT', 'DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY',
            'CREDENTIAL_ENCRYPTION_KEY', 'BACKEND_CORS_ORIGINS'],
    'worker': ['ENVIRONMENT', 'DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY',
               'CREDENTIAL_ENCRYPTION_KEY', 'DAYTONA_API_KEY', 'DAYTONA_SANDBOX_IMAGE'],
}
if role not in required:
    raise SystemExit('Choose api, worker, or frontend.')
missing = [name for name in required[role] if not os.environ.get(name)
           and not (name == 'NEXT_PUBLIC_SUPABASE_ANON_KEY' and os.environ.get('NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY'))]
for name in required[role]:
    print(f'{name}: {"MISSING" if name in missing else "set"}')
raise SystemExit(1 if missing else 0)
