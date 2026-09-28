"""Bounded public GitHub archive ingestion. No git binary, hooks or host execution."""
import re
from urllib.parse import urlsplit, quote
import httpx
from backend.app.services.zip_import import ZipImportService, ZipValidationError


def archive_url(url, branch='main'):
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ZipValidationError("Invalid repository URL.") from exc
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com' or
            parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ZipValidationError('Only public https://github.com/owner/repository URLs are supported.')
    parts = parsed.path.strip('/').split('/')
    if len(parts) != 2 or not all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', p) for p in parts):
        raise ZipValidationError('Provide a GitHub repository URL without a branch or file path.')
    owner, repo = parts
    repo = repo.removesuffix('.git')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,199}', branch) or '..' in branch or '//' in branch:
        raise ZipValidationError('Invalid repository branch.')
    return f'https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{quote(branch, safe="")}'


async def public_repository_files(url, branch='main', transport=None):
    endpoint = archive_url(url, branch)
    data = bytearray()
    # Fixed destination, no credentials/proxies/redirects, bounded streamed body.
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False, transport=transport) as client:
        async with client.stream('GET', endpoint) as response:
            if response.status_code != 200:
                raise ZipValidationError('Public repository or branch unavailable; private repositories and redirects are unsupported.')
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > ZipImportService.MAX_ZIP_BYTES:
                    raise ZipValidationError('Repository archive exceeds import size quota.')
    with ZipImportService.validate_zip_stream(bytes(data)) as archive:
        entries = ZipImportService.sanitize_and_inspect_members(archive)
        files = ZipImportService.extract_entries(archive, entries)
    roots = {item['relative_path'].split('/')[0] for item in files}
    if len(roots) != 1 or any('/' not in item['relative_path'] for item in files):
        raise ZipValidationError('Invalid repository archive layout.')
    for item in files:
        item['relative_path'] = item['relative_path'].split('/', 1)[1]
    if any(item['relative_path'] == '.gitmodules' for item in files):
        raise ZipValidationError('Repositories requiring submodules are unsupported; import a complete ZIP instead.')
    return files
