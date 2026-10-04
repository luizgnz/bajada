"""Explicit limits keep playlists, saved state and worker output bounded."""
MAX_PLAYLIST_ITEMS = 1000
MAX_SCAN_ITEMS = 200000
MAX_LEGACY_ITEMS = 2000
MAX_STATE_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
METADATA_TIMEOUT = 180
DOWNLOAD_TIMEOUT = 6 * 60 * 60
INACTIVITY_TIMEOUT = 180
CONVERSION_INACTIVITY_TIMEOUT = 20 * 60
MIN_FREE_BYTES = 50 * 1024 * 1024
MAX_CONSECUTIVE_FAILURES = 5


class PlaylistLimitError(ValueError):
    pass


def playlist_items(info, allow_empty=False):
    if not isinstance(info, dict):
        raise ValueError('YouTube devolvió una respuesta inválida. Prueba otra vez.')
    count = info.get('playlist_count')
    entries = info.get('entries') if info.get('_type') in ('playlist', 'multi_video') else [info]
    if (isinstance(count, (int, float)) and count > MAX_PLAYLIST_ITEMS or
            isinstance(entries, list) and len(entries) > MAX_PLAYLIST_ITEMS):
        raise PlaylistLimitError(f'Esta playlist supera el límite de {MAX_PLAYLIST_ITEMS} elementos. Usa una lista más pequeña. Tu cola anterior se conserva.')
    if not isinstance(entries, list):
        raise ValueError('No se pudo leer la lista de videos.')
    items = []
    for entry in entries:
        if entry is None:
            continue
        if not isinstance(entry, dict):
            raise ValueError('La playlist contiene información inválida.')
        video_id = entry.get('id')
        if not video_id:
            continue
        if not isinstance(video_id, str) or not video_id or len(video_id) > 128:
            raise ValueError('YouTube devolvió un identificador inválido.')
        title = entry.get('title') or 'Video sin título'
        if not isinstance(title, str):
            raise ValueError('YouTube devolvió un título inválido.')
        items.append({'title': title[:2000], 'url': 'https://www.youtube.com/watch?v=' + video_id,
                      'status': 'pending', 'selected': True})
    if not items and not allow_empty:
        raise ValueError('No hay videos disponibles en este enlace.')
    return items
