"""GitHub release checks and atomic AppImage updates."""
from i18n import tr
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from version import __version__

REPOSITORY = 'gsanmartindougan/Estante'
RELEASES_URL = 'https://github.com/' + REPOSITORY + '/releases'
MAX_DOWNLOAD = 512 * 1024 * 1024


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value)
    if not match:
        raise ValueError(tr('La publicación no tiene una versión válida (ejemplo: v0.1.0).'))
    return tuple(map(int, match.groups()))


def latest_release(current=__version__):
    request = Request('https://api.github.com/repos/' + REPOSITORY + '/releases/latest',
                      headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'Estante/' + current})
    try:
        with urlopen(request, timeout=20) as response:
            release = json.loads(response.read(2_000_001))
    except HTTPError as error:
        if error.code == 404:
            raise ValueError(tr('Todavía no hay una versión pública disponible en GitHub.')) from error
        if error.code == 403:
            raise ValueError(tr('GitHub no permite consultar ahora. Inténtalo más tarde.')) from error
        raise
    if release.get('draft') or release.get('prerelease'):
        return None
    tag = release.get('tag_name', '')
    if version_tuple(tag) <= version_tuple(current):
        return None
    version = tag.removeprefix('v')
    expected_name = f'Estante-{version}-x86_64.AppImage'
    asset = next((item for item in release.get('assets', []) if item.get('name') == expected_name), None)
    return {'version': version, 'asset': asset, 'url': RELEASES_URL + '/tag/' + tag}


def appimage_path():
    value = os.environ.get('APPIMAGE')
    return Path(value).expanduser().resolve() if value and os.environ.get('ESTANTE_APPDIR') else None


def update_available(release, target=None):
    if platform.machine() != 'x86_64':
        return tr('No hay AppImage para esta arquitectura.')
    if target is None:
        return tr('La actualización integrada requiere ejecutar el AppImage. Para esta instalación, descarga el instalador de la nueva versión.')
    if not target.is_file() or not os.access(target.parent, os.W_OK):
        return tr('No se puede escribir en la carpeta del AppImage. Mueve el archivo a una carpeta de tu usuario.')
    asset = release.get('asset')
    if not asset:
        return tr('La publicación todavía no incluye el AppImage para x86_64.')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', asset.get('digest') or ''):
        return tr('GitHub todavía no ofrece la suma SHA-256 de este archivo.')
    return ''


def install_appimage(release, target):
    target = Path(target).resolve()
    reason = update_available(release, target)
    if reason:
        raise ValueError(reason)
    asset = release['asset']
    address = asset.get('browser_download_url', '')
    parsed = urlparse(address)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not parsed.path.startswith('/' + REPOSITORY + '/releases/download/'):
        raise ValueError(tr('La descarga no pertenece al repositorio de Estante.'))
    expected_size = asset.get('size', 0)
    if not isinstance(expected_size, int) or not 0 < expected_size <= MAX_DOWNLOAD:
        raise ValueError(tr('El tamaño de la actualización no es válido.'))
    checksum = asset['digest'].split(':', 1)[1].lower()
    descriptor, name = tempfile.mkstemp(prefix='.estante-update-', dir=target.parent)
    candidate = Path(name)
    try:
        digest = hashlib.sha256()
        total = 0
        with os.fdopen(descriptor, 'wb') as output:
            request = Request(address, headers={'User-Agent': 'Estante/' + __version__})
            with urlopen(request, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > expected_size:
                        raise ValueError(tr('La descarga supera el tamaño esperado.'))
                    digest.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if total != expected_size or digest.hexdigest() != checksum:
            raise ValueError(tr('La descarga está incompleta o su SHA-256 no coincide. Se conserva la versión anterior.'))
        with candidate.open('rb') as image:
            header = image.read(11)
        if header[:4] != b'\x7fELF' or header[8:11] != b'AI\x02':
            raise ValueError(tr('El archivo descargado no es un AppImage válido.'))
        candidate.chmod(0o755)
        os.replace(candidate, target)
        return release['version']
    finally:
        candidate.unlink(missing_ok=True)
