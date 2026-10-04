"""Queue persistence and download arguments, independent of the interface."""
import json
import os
import sys
import shutil
import tempfile
import re
import errno
from pathlib import Path
from urllib.parse import urlparse
from limits import MAX_STATE_BYTES, MAX_LEGACY_ITEMS


def youtube_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 8192:
        raise ValueError('Pega un enlace de YouTube válido.')
    parsed = urlparse(value.strip())
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in ('https', 'http') or host not in (
        'youtube.com', 'www.youtube.com', 'm.youtube.com',
        'music.youtube.com', 'youtu.be', 'www.youtu.be',
    ) or parsed.username or parsed.password:
        raise ValueError('Pega un enlace de YouTube válido.')
    return value.strip()


def state_directory():
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share'))
    target = base / 'DescargaFacil'
    target.mkdir(parents=True, exist_ok=True)
    return target


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    if len(payload.encode('utf-8')) > MAX_STATE_BYTES:
        raise ValueError('La cola supera el tamaño permitido para guardarla.')
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name, suffix='.tmp', delete=False) as stream:
            name = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            # Keep a known-valid previous state before replacing the main file.
            try:
                if path.stat().st_size > MAX_STATE_BYTES:
                    raise ValueError('Oversized saved state')
                previous = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(previous, dict) or len(previous.get('items', [])) > MAX_LEGACY_ITEMS:
                    raise ValueError('Invalid previous state')
                shutil.copy2(path, path.with_suffix('.bak'))
            except ValueError:
                # Preserve malformed/oversized previous content for recovery.
                recovery = path.with_name(path.stem + '.recovery.json')
                if not recovery.exists():
                    shutil.copy2(path, recovery)
            except OSError:
                pass
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def load_state(path):
    state = {}
    for candidate in (path, path.with_suffix('.bak')):
        try:
            if candidate.stat().st_size > MAX_STATE_BYTES:
                raise ValueError('Oversized saved state')
            state = json.loads(candidate.read_text(encoding='utf-8'))
            if not isinstance(state, dict) or not isinstance(state.get('items', []), list):
                raise ValueError('Invalid queue')
            if len(state.get('items', [])) > MAX_LEGACY_ITEMS:
                raise ValueError('Oversized saved queue')
            if not isinstance(state.get('settings', {}), dict):
                raise ValueError('Invalid settings')
            if 'folder' in state.get('settings', {}) and not isinstance(state['settings']['folder'], str):
                raise ValueError('Invalid folder')
            for key in ('url', 'source_url'):
                if key in state and (not isinstance(state[key], str) or len(state[key]) > 8192):
                    raise ValueError('Invalid source')
            for item in state.get('items', []):
                if not isinstance(item, dict) or item.get('status') not in ('pending', 'downloading', 'done', 'failed'):
                    raise ValueError('Invalid entry')
                if not isinstance(item.get('title'), str) or len(item['title']) > 2000:
                    raise ValueError('Invalid title')
                if 'settings' in item and not isinstance(item['settings'], dict):
                    raise ValueError('Invalid item settings')
                if 'url' in item:
                    youtube_url(item['url'])
                for key in ('file', 'error', 'original_title'):
                    if key in item and (not isinstance(item[key], str) or len(item[key]) > 8192):
                        raise ValueError('Invalid stored field')
                if 'selected' in item and not isinstance(item['selected'], bool):
                    raise ValueError('Invalid selection')
            break
        except (ValueError, OSError):
            state = {}
    for item in state.get('items', []):
        if item['status'] == 'downloading':
            item['status'] = 'pending'
    return state


def verify_package(root):
    import hashlib
    try:
        manifest = json.loads((root / 'components.json').read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or not manifest:
            raise ValueError('Inventario vacío')
        for relative, expected in manifest.items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                return 'Falta un archivo del instalador: ' + relative
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                return 'Archivo incompleto o alterado: ' + relative
        return 'OK'
    except (OSError, ValueError, TypeError) as exc:
        return 'No se pudo verificar el paquete: ' + str(exc)


def dependency_report():
    import importlib
    import subprocess
    results = {}
    if getattr(sys, 'frozen', False):
        results['archivos instalados'] = verify_package(Path(sys._MEIPASS))
    for module in ('yt_dlp', 'yt_dlp_ejs', 'PySide6.QtCore', 'PySide6.QtWidgets'):
        try:
            importlib.import_module(module)
            results[module] = 'OK'
        except Exception as exc:
            results[module] = str(exc)
    for tool in ('ffmpeg', 'ffprobe', 'deno'):
        bundled = binary_directory() / (tool + ('.exe' if os.name == 'nt' else ''))
        binary = str(bundled) if bundled.is_file() else (None if getattr(sys, 'frozen', False) else shutil.which(tool))
        try:
            if not binary:
                raise FileNotFoundError('No incluido')
            flag = '--version' if tool == 'deno' else '-version'
            kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
            check = subprocess.run([binary, flag], capture_output=True, text=True, timeout=15, **kwargs)
            if check.returncode:
                raise RuntimeError('No se pudo ejecutar')
            results[tool] = 'OK'
        except Exception as exc:
            results[tool] = str(exc)
    return results


def engine_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--engine']
    return [sys.executable, '-m', 'yt_dlp']


def binary_directory():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    return root / 'vendor'


def music_title(metadata):
    """Use explicit music fields, never infer an artist from a channel name."""
    track = metadata.get('track')
    artists = metadata.get('artists')
    if isinstance(artists, list):
        artist = ', '.join(a.strip() for a in artists if isinstance(a, str) and a.strip())
    else:
        artist = metadata.get('artist')
    if not isinstance(track, str) or not track.strip() or not isinstance(artist, str) or not artist.strip():
        return None
    track, artist = ' '.join(track.split()), ' '.join(artist.split())
    # Retain version labels so a live performance is not presented as a studio recording.
    original = metadata.get('title') if isinstance(metadata.get('title'), str) else ''
    for qualifier in re.findall(r'[\[(]([^\])]+)[\])]', original):
        if re.search(r'\ben vivo\b|\blive\b|unplugged|ac[uú]stic|remaster', qualifier, re.I):
            if qualifier.casefold() not in track.casefold():
                track += f' ({qualifier})'
    return f'{artist} - {track}'


def clean_download_name(path, metadata=None, audio=False):
    """Remove only a trailing YouTube ID, preserving other bracketed title text."""
    path = Path(path)
    stem = re.sub(r'\s*\[[A-Za-z0-9_-]{11}\]$', '', path.stem).strip()
    preferred = music_title(metadata or {}) if audio else None
    if preferred:
        from yt_dlp.utils import sanitize_filename
        stem = sanitize_filename(preferred, restricted=False, is_id=False)
        # Stay below Windows filename limits even with multi-byte characters.
        stem = stem.encode('utf-8')[:180].decode('utf-8', errors='ignore').rstrip(' .')
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', stem, re.I):
        stem = '_' + stem
    return path.with_name((stem or 'Sin título') + path.suffix)


def rename_without_overwrite(source, target):
    """Atomic hardlink move on supported disks; exclusive copy fallback elsewhere."""
    source, target = Path(source), Path(target)
    if source == target:
        return source
    if source.is_symlink() or not source.is_file():
        raise OSError('No se puede renombrar el archivo terminado.')
    number = 1
    while True:
        candidate = target if number == 1 else target.with_name(f'{target.stem} ({number}){target.suffix}')
        try:
            os.link(source, candidate)
        except FileExistsError:
            number += 1
            continue
        except OSError as exc:
            if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.ENOSYS):
                raise
            try:
                stream = candidate.open('xb')
            except FileExistsError:
                number += 1
                continue
            try:
                with stream, source.open('rb') as incoming:
                    shutil.copyfileobj(incoming, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                candidate.unlink(missing_ok=True)
                raise
        try:
            source.unlink()
        except OSError:
            candidate.unlink(missing_ok=True)
            raise
        return candidate


def finish_download(path, metadata=None, audio=False):
    return str(rename_without_overwrite(path, clean_download_name(path, metadata, audio)))


def download_arguments(item, settings):
    if not isinstance(settings, dict) or not isinstance(item, dict):
        raise ValueError('Los ajustes guardados no son válidos. Vuelve a procesar el enlace.')
    mode, fmt, quality = settings.get('mode'), settings.get('format'), settings.get('quality')
    allowed = ('MP3', 'M4A', 'AAC', 'FLAC') if mode == 'audio' else ('MP4', 'MKV', 'WebM', 'MOV', 'AVI')
    folder_name = settings.get('folder')
    if mode not in ('audio', 'video') or fmt not in allowed or not isinstance(folder_name, str) or not folder_name or '\x00' in folder_name:
        raise ValueError('Los ajustes de descarga no son válidos. Vuelve a procesar el enlace.')
    if mode == 'video' and quality not in ('480p', '720p', '1080p', 'Mejor disponible'):
        raise ValueError('La calidad de video no es válida.')
    if mode == 'audio' and quality not in ('128kbps', '192kbps', '256kbps', 'lossless', None):
        raise ValueError('La calidad de audio no es válida.')
    if not item.get('url'):
        raise ValueError('Este elemento no tiene un enlace válido. Vuelve a procesar la playlist.')
    folder = Path(folder_name)
    args = [
        '--ignore-config', '--no-playlist', '--newline', '--no-colors', '--no-warnings',
        '--progress-template', 'download:DF_PROGRESS:%(progress._percent_str)s',
        '--print', 'after_move:DF_FILE:%(filepath)s', '--progress',
        '--print', 'after_move:DF_META:%(.{id,title,track,artists,artist,album})j',
        '--windows-filenames', '--continue', '--no-overwrites',
        '--socket-timeout', '20', '--retries', '3', '--fragment-retries', '3',
        # The ID keeps partial downloads separate. finish_download removes it on completion.
        '-P', str(folder), '-o', '%(title).160B [%(id)s].%(ext)s',
    ]
    vendor = binary_directory()
    if (vendor / 'ffmpeg.exe').exists():
        args += ['--ffmpeg-location', str(vendor)]
    if (vendor / 'deno.exe').exists():
        args += ['--js-runtimes', 'deno:' + str(vendor / 'deno.exe')]
    fmt = settings['format']
    if settings['mode'] == 'audio':
        quality = settings.get('quality', '192kbps')
        rate = quality.removesuffix('kbps') if quality in ('128kbps', '192kbps', '256kbps') else '192'
        source = 'ba[acodec=opus]/bestaudio/best' if fmt in ('AAC', 'M4A') else 'bestaudio/best'
        args += ['-f', source, '-x', '--audio-format', fmt.lower(),
                 '--embed-metadata', '--no-embed-chapters', '--no-embed-info-json']
        if fmt != 'FLAC':
            args += ['--audio-quality', rate + 'K']
    else:
        height = settings['quality']
        limit = '' if height == 'Mejor disponible' else '[height<=' + height.removesuffix('p') + ']'
        if fmt == 'MP4':
            # H.264/AAC preserves broad compatibility, without forcing an expensive re-encode.
            choice = f'bv[vcodec^=avc1]{limit}+ba[ext=m4a]/b[ext=mp4]{limit}'
        elif fmt == 'WebM':
            choice = f'bv[ext=webm]{limit}+ba[ext=webm]/b[ext=webm]{limit}'
        else:
            choice = f'bv{limit}+ba/b{limit}'
        if fmt in ('MOV', 'AVI'):
            args += ['-f', f'bv[vcodec^=avc1]{limit}+ba[ext=m4a]/b[ext=mp4]{limit}', '--merge-output-format', 'mp4', '--recode-video', fmt.lower()]
        else:
            args += ['-f', choice, '--merge-output-format', fmt.lower(), '--remux-video', fmt.lower()]
    args += ['--', youtube_url(item['url'])]
    return args
