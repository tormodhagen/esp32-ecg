"""Public GitHub release discovery and bounded, digest-verified downloads."""
import hashlib
import json
from pathlib import Path
import re
import urllib.request
from ota_update import check_image
MAX_IMAGE = 0x1E0000

def latest_release(repository):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Enter a public GitHub repository as owner/repository.')
    req = urllib.request.Request(f'https://api.github.com/repos/{repository}/releases/latest', headers={
        'Accept':'application/vnd.github+json', 'User-Agent':'ECG-Monitor', 'X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read(2_000_001)
    if len(data)>2_000_000: raise ValueError('Release metadata too large')
    release = json.loads(data)
    if release.get('draft') or release.get('prerelease'): raise ValueError('Expected a stable published release')
    assets = [a for a in release.get('assets', []) if a.get('name','').lower().endswith('.bin') and 24<=a.get('size',0)<=MAX_IMAGE]
    if not assets: raise ValueError('No application .bin found in the latest release.')
    return {'tag':release['tag_name'], 'notes':release.get('body') or '', 'assets':assets}

def download_asset(asset, destination):
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/'):
        raise ValueError('Expected a GitHub HTTPS release asset')
    digest = asset.get('digest') or ''
    if not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest):
        raise ValueError('GitHub did not provide a SHA-256 digest. Download manually and use Local firmware instead.')
    req = urllib.request.Request(url, headers={'User-Agent':'ECG-Monitor'})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read(MAX_IMAGE+1)
    if len(data)!=asset['size'] or len(data)>MAX_IMAGE: raise ValueError('Firmware download size mismatch')
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower()!=digest.split(':')[1].lower(): raise ValueError('Firmware SHA-256 mismatch')
    destination = Path(destination); destination.mkdir(parents=True,exist_ok=True)
    path = destination/(actual+'.bin'); temporary = path.with_suffix('.part')
    try:
        temporary.write_bytes(data); check_image(temporary); temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return str(path)
