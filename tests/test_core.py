import pytest
from core import youtube_url, save_state, load_state, download_arguments
from core import clean_download_name, finish_download, music_title

@pytest.mark.parametrize('url', ['https://youtu.be/abc', 'https://www.youtube.com/playlist?list=abc', 'https://music.youtube.com/watch?v=abc'])
def test_youtube_urls(url):
    assert youtube_url(url) == url

@pytest.mark.parametrize('url', ['https://youtube.com.evil.test/watch?v=x', 'file:///tmp/x', 'https://user@youtube.com/x', 'https://vimeo.com/123'])
def test_other_hosts_rejected(url):
    with pytest.raises(ValueError):
        youtube_url(url)


def test_400_items_recover_only_interrupted(tmp_path):
    path = tmp_path / 'queue.json'
    items = [{'status': 'done' if i < 125 else 'pending', 'title': f'Video {i}'} for i in range(400)]
    items[125]['status'] = 'downloading'
    items[126]['status'] = 'failed'
    save_state(path, {'items': items})
    restored = load_state(path)['items']
    assert len(restored) == 400
    assert sum(i['status'] == 'done' for i in restored) == 125
    assert restored[125]['status'] == 'pending'
    assert restored[126]['status'] == 'failed'


def test_formats_and_output_path(tmp_path):
    item = {'url': 'https://youtu.be/abc'}
    base = {'folder': str(tmp_path / 'Folder with spaces'), 'mode': 'video', 'quality': '720p', 'format': 'MP4'}
    args = download_arguments(item, base)
    assert args[args.index('-P') + 1] == base['folder']
    assert '[height<=720]' in args[args.index('-f') + 1]
    assert 'avc1' in args[args.index('-f') + 1]
    assert args[-2:] == ['--', item['url']]
    audio = download_arguments(item, {**base, 'mode': 'audio', 'format': 'MP3', 'quality':'192kbps'})
    assert audio[audio.index('--audio-format') + 1] == 'mp3'
    assert '-x' in audio


def test_corrupted_queue_recovers_previous_valid_save(tmp_path):
    path = tmp_path / 'queue.json'
    save_state(path, {'items': [{'status': 'done', 'title': 'Completado'}]})
    save_state(path, {'items': [{'status': 'pending', 'title': 'Nuevo'}]})
    path.write_text('{broken', encoding='utf-8')
    assert load_state(path)['items'][0]['title'] == 'Completado'
    assert not list(tmp_path.glob('*.tmp'))


def test_failed_write_preserves_previous_queue(tmp_path, monkeypatch):
    import core
    path = tmp_path / 'queue.json'
    previous = {'items': [{'status': 'done', 'title': 'Ya terminado'}]}
    save_state(path, previous)
    def denied(*args):
        raise PermissionError('No space')
    monkeypatch.setattr(core.os, 'replace', denied)
    with pytest.raises(PermissionError):
        save_state(path, {'items': []})
    assert load_state(path) == previous
    assert not list(tmp_path.glob('*.tmp'))


def test_installer_inventory_detects_missing_or_damaged_files(tmp_path):
    import json, hashlib
    from core import verify_package
    binary = tmp_path / 'ffmpeg.exe'
    binary.write_bytes(b'complete-runtime')
    manifest = {'ffmpeg.exe': hashlib.sha256(binary.read_bytes()).hexdigest()}
    (tmp_path / 'components.json').write_text(json.dumps(manifest))
    assert verify_package(tmp_path) == 'OK'
    binary.write_bytes(b'incomplete')
    assert 'incompleto' in verify_package(tmp_path)
    binary.unlink()
    assert 'Falta un archivo' in verify_package(tmp_path)

@pytest.mark.parametrize('quality,rate', [('128kbps','128K'),('192kbps','192K'),('256kbps','256K')])
def test_audio_quality(quality, rate, tmp_path):
    args = download_arguments({'url':'https://youtu.be/example'}, {'folder':str(tmp_path),'mode':'audio','format':'MP3','quality':quality})
    assert args[args.index('--audio-quality') + 1] == rate

@pytest.mark.parametrize('fmt', ['MOV','AVI'])
def test_extra_video_formats_use_conversion(fmt, tmp_path):
    args = download_arguments({'url':'https://youtu.be/example'}, {'folder':str(tmp_path),'mode':'video','format':fmt,'quality':'720p'})
    assert args[args.index('--recode-video') + 1] == fmt.lower()


def test_clean_names_preserve_meaningful_brackets_and_extensions(tmp_path):
    original = tmp_path / 'Artista - Canción [MTV Unplugged] [kbJu9LPQAGE].mp3'
    original.write_bytes(b'audio')
    result = finish_download(original)
    assert result == str(tmp_path / 'Artista - Canción [MTV Unplugged].mp3')
    assert not original.exists()
    assert clean_download_name(tmp_path / 'Canción [En vivo].m4a').name == 'Canción [En vivo].m4a'
    assert clean_download_name(tmp_path / 'CON [abcdefghijk].mp3').name == '_CON.mp3'


def test_equal_titles_do_not_overwrite_either_song(tmp_path):
    existing = tmp_path / 'Canción.mp3'
    existing.write_bytes(b'first')
    original = tmp_path / 'Canción [abcdefghijk].mp3'
    original.write_bytes(b'second')
    result = finish_download(original)
    assert result == str(tmp_path / 'Canción (2).mp3')
    assert existing.read_bytes() == b'first'
    assert (tmp_path / 'Canción (2).mp3').read_bytes() == b'second'


def test_music_names_require_track_and_artist_preserving_version(tmp_path):
    metadata = {'title': 'Video promocional (En Vivo)', 'track': 'Así Fue', 'artists': ['Juan Gabriel']}
    assert music_title(metadata) == 'Juan Gabriel - Así Fue (En Vivo)'
    assert music_title({'title': 'Video', 'track': 'Canción', 'uploader': 'Canal'}) is None
    original = tmp_path / 'Video [abcdefghijk].mp3'
    original.write_bytes(b'audio')
    assert finish_download(original, metadata, audio=True).endswith('Juan Gabriel - Así Fue (En Vivo).mp3')
    assert clean_download_name(tmp_path / 'Video [abcdefghijk].mp4', metadata, audio=False).name == 'Video.mp4'


def test_unsafe_music_title_stays_in_same_folder(tmp_path):
    path = clean_download_name(tmp_path / 'Video [abcdefghijk].mp3',
                               {'track': '../Canción: "Especial"?', 'artist': 'Artista/Grupo'}, audio=True)
    assert path.parent == tmp_path
    assert not any(ch in path.name for ch in ':"?<>|\\/')


def test_rename_fallback_on_disks_without_hardlinks(tmp_path, monkeypatch):
    import core, errno
    def unsupported(*args):
        raise OSError(errno.ENOTSUP, 'No hardlinks')
    monkeypatch.setattr(core.os, 'link', unsupported)
    (tmp_path / 'Canción.mp3').write_bytes(b'first')
    source = tmp_path / 'Canción [abcdefghijk].mp3'
    source.write_bytes(b'second')
    assert finish_download(source).endswith('Canción (2).mp3')
    assert (tmp_path / 'Canción.mp3').read_bytes() == b'first'
    assert not source.exists()
