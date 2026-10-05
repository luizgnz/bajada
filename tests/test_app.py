import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import time
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from main import Window, Engine
import main

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert predicate()


def test_open_folder_creates_missing_destination(app, tmp_path, monkeypatch):
    window = Window(tmp_path / 'queue.json')
    folder = tmp_path / 'Música nueva' / 'Bajada'
    window.folder.setText(str(folder))
    opened = []
    if os.name == 'nt':
        monkeypatch.setattr(main.os, 'startfile', opened.append)
    else:
        monkeypatch.setattr(main.QDesktopServices, 'openUrl', lambda url: opened.append(url.toLocalFile()) or True)
    window.open_folder.click()
    assert folder.is_dir()
    assert opened == [str(folder.resolve())]
    window.close()


def test_open_folder_reports_invalid_destination(app, tmp_path, monkeypatch):
    window = Window(tmp_path / 'queue.json')
    folder = tmp_path / 'file'
    folder.write_text('existing file')
    window.folder.setText(str(folder))
    errors = []
    monkeypatch.setattr(window, 'show_error', errors.append)
    window.open_folder.click()
    assert len(errors) == 1
    assert 'No se pudo abrir la carpeta' in errors[0]
    assert folder.read_text() == 'existing file'
    window.close()


def test_large_list_selection_and_restoration(app, tmp_path):
    window = Window(tmp_path / 'queue.json')
    window.inspected({'_type': 'playlist', 'entries': [{'id': str(i), 'title': f'Video {i}'} for i in range(100)]})
    assert window.table.rowCount() == 100
    window.range_input.setText('1-50, 80')
    window.choose_range()
    assert sum(item['selected'] for item in window.items) == 51
    window.close()
    restored = Window(tmp_path / 'queue.json')
    assert len(restored.items) == 100
    assert sum(item['selected'] for item in restored.items) == 51
    restored.close()


def test_worker_progress_and_final_file(app, tmp_path, monkeypatch):
    target = tmp_path / 'completed.mp4'
    target.write_bytes(b'test')
    script = "print('DF_PROGRESS: 70.0%'); print('DF_FILE:' + " + repr(str(target)) + ')'
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', script])
    worker = Engine([])
    values, results = [], []
    worker.progress.connect(values.append)
    worker.result.connect(results.append)
    worker.start()
    wait_for(app, lambda: not worker.isRunning())
    assert values == [70]
    assert results == [str(target)]


def test_worker_does_not_inherit_detached_console_input(app, tmp_path, monkeypatch):
    target = tmp_path / 'completed.mp4'
    target.write_bytes(b'test')
    script = "print('DF_FILE:' + " + repr(str(target)) + ')'
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', script])
    original_popen = main.subprocess.Popen
    def detached_console_popen(*args, **kwargs):
        if kwargs.get('stdin') is None:
            raise OSError(50, 'The request is not supported')
        return original_popen(*args, **kwargs)
    monkeypatch.setattr(main.subprocess, 'Popen', detached_console_popen)
    worker = Engine([])
    results, errors = [], []
    worker.result.connect(results.append)
    worker.problem.connect(errors.append)
    worker.start()
    wait_for(app, lambda: not worker.isRunning())
    assert not errors
    assert results == [str(target)]


def test_download_creates_destination_without_installer(app, tmp_path, monkeypatch):
    folder = tmp_path / 'Videos nuevos' / 'Bajada'
    target = folder / 'completed.mp4'
    script = "from pathlib import Path; p = Path(" + repr(str(target)) + "); assert p.parent.is_dir(); p.write_bytes(b'test'); print('DF_FILE:' + str(p))"
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', script])
    worker = Engine(['-P', str(folder)])
    results, errors = [], []
    worker.result.connect(results.append)
    worker.problem.connect(errors.append)
    worker.start()
    wait_for(app, lambda: not worker.isRunning())
    assert not errors
    assert target.read_bytes() == b'test'
    assert results == [str(target)]


def test_worker_rejects_missing_output(app, tmp_path, monkeypatch):
    script = "print('DF_FILE:' + " + repr(str(tmp_path / 'missing.mp4')) + ')'
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', script])
    worker = Engine([])
    errors = []
    worker.problem.connect(errors.append)
    worker.start()
    wait_for(app, lambda: not worker.isRunning())
    assert errors and 'archivo terminado' in errors[0]


def test_cancel_returns_pending_and_preserves_queue(app, tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', 'import time; time.sleep(20)'])
    window = Window(tmp_path / 'queue.json')
    window.folder.setText(str(tmp_path))
    window.inspected({'id': 'test', 'title': 'Prueba'})
    monkeypatch.setattr(main.shutil, 'which', lambda name: 'mock-ffmpeg')
    window.start_queue()
    wait_for(app, lambda: window.worker is not None and window.worker.process is not None)
    window.cancel_queue()
    wait_for(app, lambda: not window.running and window.worker is None)
    assert window.items[0]['status'] == 'pending'
    window.close()


def test_queue_continues_after_failure(app, tmp_path, monkeypatch):
    script = """import sys
from pathlib import Path
url = sys.argv[-1]
if url.endswith('bad'):
    print('ERROR: unavailable')
    sys.exit(1)
p = Path(sys.argv[sys.argv.index('-P') + 1]) / (url.rsplit('=', 1)[-1] + '.mp4')
p.write_bytes(b'demo')
print('DF_FILE:' + str(p))
"""
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', script])
    window = Window(tmp_path / 'queue.json')
    window.folder.setText(str(tmp_path))
    window.inspected({'_type': 'playlist', 'entries': [{'id': i, 'title': i} for i in ['first', 'bad', 'last']]})
    monkeypatch.setattr(main.shutil, 'which', lambda name: 'mock-ffmpeg')
    window.start_queue()
    wait_for(app, lambda: not window.running and window.worker is None)
    assert [i['status'] for i in window.items] == ['done', 'failed', 'done']
    monkeypatch.setattr(main.shutil, 'which', lambda name: 'mock-ffmpeg')
    window.start_queue()
    assert [i['status'] for i in window.items] == ['done', 'failed', 'done']
    window.close()


def test_pause_finishes_current_without_starting_next(app, tmp_path, monkeypatch):
    script = """import sys, time
from pathlib import Path
time.sleep(0.1)
p = Path(sys.argv[sys.argv.index('-P') + 1]) / 'one.mp4'
p.write_bytes(b'demo')
print('DF_FILE:' + str(p))
"""
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', script])
    window = Window(tmp_path / 'queue.json')
    window.folder.setText(str(tmp_path))
    window.inspected({'_type': 'playlist', 'entries': [{'id': i, 'title': i} for i in ['one', 'two']]})
    monkeypatch.setattr(main.shutil, 'which', lambda name: 'mock-ffmpeg')
    window.start_queue()
    window.pause_queue()
    wait_for(app, lambda: not window.running and window.worker is None)
    assert [i['status'] for i in window.items] == ['done', 'pending']
    window.close()


def test_status_update_does_not_rebuild_playlist(app, tmp_path, monkeypatch):
    window = Window(tmp_path / 'queue.json')
    window.inspected({'_type': 'playlist', 'entries': [{'id': str(i), 'title': str(i)} for i in range(100)]})
    cell = window.table.item(99, 2)
    window.current = window.items[0]
    window.current['status'] = 'done'
    window.update_current_row()
    assert window.table.item(99, 2) is cell
    assert window.table.item(0, 3).text() == 'Completado'
    window.close()


def test_worker_coalesces_duplicate_progress(app, tmp_path, monkeypatch):
    target = tmp_path / 'ready.mp4'
    target.write_bytes(b'demo')
    script = "for i in range(200): print('DF_PROGRESS: 70.0%')\nprint('DF_FILE:' + " + repr(str(target)) + ')'
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', script])
    worker = Engine([])
    values = []
    worker.progress.connect(values.append)
    worker.start()
    wait_for(app, lambda: not worker.isRunning())
    assert values == [70]


def test_save_failure_pauses_instead_of_crashing(app, tmp_path, monkeypatch):
    window = Window(tmp_path / 'queue.json')
    def denied(*args):
        raise PermissionError('Disk full')
    monkeypatch.setattr(main, 'save_state', denied)
    window.running = True
    window.persist()
    assert window.pause_requested
    assert 'No se pudo guardar' in window.status.text()
    window.running = False
    window.close()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX descendant test; Windows uses taskkill /T')
def test_cancel_terminates_conversion_child(app, tmp_path, monkeypatch):
    marker = tmp_path / 'should-not-exist'
    ready = tmp_path / 'child-ready'
    child_script = 'import time; from pathlib import Path; Path(' + repr(str(ready)) + ').touch(); time.sleep(2); Path(' + repr(str(marker)) + ').write_text("orphan")'
    parent_script = 'import subprocess, sys, time; subprocess.Popen([sys.executable, "-c", ' + repr(child_script) + ']); print("started", flush=True); time.sleep(20)'
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', parent_script])
    worker = Engine([])
    errors = []
    worker.problem.connect(errors.append)
    worker.start()
    wait_for(app, lambda: ready.exists())
    worker.stop()
    wait_for(app, lambda: not worker.isRunning())
    assert errors and 'detenida' in errors[0]
    deadline = time.monotonic() + 2.1
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not marker.exists()


def test_audio_is_default_even_after_previous_video_session(app, tmp_path):
    from core import save_state
    path = tmp_path / 'queue.json'
    save_state(path, {'items': [], 'settings': {'mode': 'video', 'format': 'MP4'}, 'url': 'https://youtu.be/old'})
    window = Window(path)
    assert window.mode.currentText() == 'Solo audio'
    assert window.format.currentText() == 'MP3'
    assert window.url.text() == ''
    assert window.analyze.text() == 'Procesar'
    assert window.quality.currentText() == 'Media (192 kbps)'
    window.close()


def test_process_reads_clipboard_when_field_empty(app, tmp_path, monkeypatch):
    window = Window(tmp_path / 'queue.json')
    app.clipboard().setText('https://www.youtube.com/playlist?list=example')
    calls = []
    monkeypatch.setattr(window, 'launch', lambda *args: calls.append(args))
    window.inspect()
    assert len(calls) == 1
    assert calls[0][0][-1] == app.clipboard().text()
    assert window.url.text() == app.clipboard().text()
    window.close()


def test_process_respects_link_typed_in_field(app, tmp_path, monkeypatch):
    window = Window(tmp_path / 'queue.json')
    app.clipboard().setText('https://youtu.be/clipboard')
    window.url.setText('https://youtu.be/typed')
    calls = []
    monkeypatch.setattr(window, 'launch', lambda *args: calls.append(args))
    window.inspect()
    assert calls[0][0][-1] == 'https://youtu.be/typed'
    window.close()


def test_new_formats_and_quality_labels(app, tmp_path):
    window = Window(tmp_path / 'queue.json')
    assert [window.format.itemText(i) for i in range(window.format.count())] == ['MP3','M4A','AAC','FLAC']
    assert window.quality.currentText() == 'Media (192 kbps)'
    window.quality.setCurrentIndex(2)
    assert window.settings()['quality'] == '128kbps'
    window.format.setCurrentText('FLAC')
    assert window.quality.count() == 1
    assert window.quality.currentData() == 'lossless'
    window.mode.setCurrentIndex(0)
    assert [window.format.itemText(i) for i in range(window.format.count())] == ['MP4','MKV','WebM','MOV','AVI']
    assert window.quality.currentText() == 'Media (720p)'
    window.quality.setCurrentIndex(0)
    assert window.settings()['quality'] == '1080p'
    window.close()


def test_sorted_rows_keep_selection_and_status_with_title(app, tmp_path):
    window = Window(tmp_path / 'queue.json')
    window.inspected({'_type': 'playlist', 'entries': [
        {'id': 'a', 'title': 'Zorro'}, {'id': 'b', 'title': 'Árbol'},
        {'id': 'c', 'title': 'Casa'}]})
    window.table.sortItems(2, Qt.AscendingOrder)
    assert [window.table.item(row, 2).text() for row in range(3)] == ['Árbol', 'Casa', 'Zorro']
    for row in range(3):
        index = window.table.item(row, 0).data(Qt.UserRole)
        assert window.table.item(row, 1).data(Qt.DisplayRole) == index + 1
        assert window.table.item(row, 2).text() == window.items[index]['title']
    chosen = window.table.item(0, 0)
    index = chosen.data(Qt.UserRole)
    chosen.setCheckState(Qt.Unchecked)
    assert not window.items[index]['selected']
    assert sum(item['selected'] for item in window.items) == 2
    assert window.select_all_check.checkState() == Qt.PartiallyChecked
    window.current = window.items[index]
    window.current['status'] = 'done'
    window.update_current_row()
    assert window.table.item(chosen.row(), 3).text() == 'Completado'
    assert window.table.item(chosen.row(), 2).text() == window.current['title']
    window.select_all_check.click()
    assert all(item['selected'] for item in window.items)
    window.select_all_check.click()
    assert not any(item['selected'] for item in window.items)
    window.close()


def test_numbers_sort_numerically_and_filter_survives_sort(app, tmp_path):
    window = Window(tmp_path / 'queue.json')
    window.inspected({'_type': 'playlist', 'entries': [
        {'id': str(i), 'title': 'Árbol' if i == 3 else f'Tema {20-i}'} for i in range(12)]})
    window.table.sortItems(1, Qt.DescendingOrder)
    assert [window.table.item(row, 1).data(Qt.DisplayRole) for row in range(12)] == list(range(12, 0, -1))
    window.search.setText('arbol')
    window.table.sortItems(2, Qt.AscendingOrder)
    app.processEvents()
    visible = [row for row in range(12) if not window.table.isRowHidden(row)]
    assert len(visible) == 1
    assert window.table.item(visible[0], 1).data(Qt.DisplayRole) == 4
    window.search.setText('10')
    assert any(window.table.item(row, 1).data(Qt.DisplayRole) == 10
               for row in range(12) if not window.table.isRowHidden(row))
    window.search.clear()
    assert all(not window.table.isRowHidden(row) for row in range(12))
    window.range_input.setText('2, 10-12')
    window.choose_range()
    assert [i + 1 for i, item in enumerate(window.items) if item['selected']] == [2, 10, 11, 12]
    window.close()


def test_titles_have_single_line_and_aligned_status(app, tmp_path):
    window = Window(tmp_path / 'queue.json')
    window.inspected({'id': 'a', 'title': 'Título largo\nsegunda línea\t final'})
    assert window.table.item(0, 2).text() == 'Título largo segunda línea final'
    assert window.table.item(0, 2).textAlignment() == window.table.item(0, 3).textAlignment()
    assert window.table.rowHeight(0) == 42
    assert not window.table.wordWrap()
    window.close()


def test_worker_uses_music_metadata_and_updates_correct_sorted_title(app, tmp_path, monkeypatch):
    import json
    target = tmp_path / 'Título del video [abcdefghijk].mp3'
    target.write_bytes(b'audio')
    metadata = {'id': 'abcdefghijk', 'title': 'Título del video', 'track': 'Canción', 'artists': ['Artista']}
    script = "print('DF_META:' + " + repr(json.dumps(metadata)) + "); print('DF_FILE:' + " + repr(str(target)) + ')'
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', script])
    window = Window(tmp_path / 'queue.json')
    window.inspected({'_type': 'playlist', 'entries': [
        {'id': 'abcdefghijk', 'title': 'Título del video'}, {'id': 'other', 'title': 'Otro video'}]})
    window.table.sortItems(2, Qt.AscendingOrder)
    window.current = window.items[0]
    window.current['settings'] = {'mode': 'audio'}
    window.launch(['-x'], window.item_done, window.item_failed)
    wait_for(app, lambda: window.worker is None)
    item = window.items[0]
    assert item['title'] == 'Artista - Canción'
    assert item['original_title'] == 'Título del video'
    assert item['file'] == str(tmp_path / 'Artista - Canción.mp3')
    assert window.table.item(0, 2).text() == 'Artista - Canción'
    assert window.table.item(0, 3).text() == 'Completado'
    assert window.items[1]['status'] == 'pending'
    window.close()


@pytest.mark.parametrize('field', ['mode', 'format', 'quality'])
def test_dropdown_below_field_mouse_keyboard_and_escape(app, tmp_path, field):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    window = Window(tmp_path / 'queue.json')
    window.show()
    app.processEvents()
    combo = getattr(window, field)
    combo.setCurrentIndex(0)
    combo.showPopup()
    app.processEvents()
    popup = combo.view().window()
    assert popup.isVisible()
    assert popup.y() > combo.mapToGlobal(QPoint(0, combo.height())).y()
    assert popup.width() == combo.width()
    QTest.keyClick(combo.view(), Qt.Key_Down)
    QTest.keyClick(combo.view(), Qt.Key_Return)
    app.processEvents()
    assert combo.currentIndex() == 1
    assert not popup.isVisible()
    combo.showPopup()
    app.processEvents()
    QTest.keyClick(combo.view(), Qt.Key_Escape)
    assert combo.currentIndex() == 1
    assert not popup.isVisible()
    combo.showPopup()
    app.processEvents()
    first = combo.view().visualRect(combo.model().index(0, combo.modelColumn()))
    QTest.mouseClick(combo.view().viewport(), Qt.LeftButton, pos=first.center())
    assert combo.currentIndex() == 0
    assert not popup.isVisible()
    window.close()


def test_fixed_medium_window_ignores_old_size_and_keeps_controls_visible(app, tmp_path):
    from core import save_state
    path = tmp_path / 'queue.json'
    save_state(path, {'items': [], 'window_size': [1800, 1200]})
    window = Window(path)
    flags = window.windowFlags()
    assert flags & Qt.WindowMinimizeButtonHint
    assert flags & Qt.WindowCloseButtonHint
    assert not flags & Qt.WindowMaximizeButtonHint
    window.show()
    app.processEvents()
    assert window.width() <= 940 and window.height() <= 760
    before = window.size()
    assert window.minimumSize() == before == window.maximumSize()
    window.resize(1600, 1000)
    app.processEvents()
    assert window.size() == before
    window.resize(500, 400)
    app.processEvents()
    assert window.size() == before
    table_before = window.table.size()
    window.status.setText('Descargando: ' + 'Un título de canción muy largo ' * 20)
    app.processEvents()
    assert window.size() == before
    assert window.table.size() == table_before
    assert window.status.toolTip() == window.status.text()
    for widget in (window.url, window.mode, window.search, window.table, window.select_all_check,
                   window.folder, window.download, window.pause, window.cancel, window.open_folder):
        top = widget.mapTo(window.centralWidget(), widget.rect().topLeft())
        bottom = widget.mapTo(window.centralWidget(), widget.rect().bottomRight())
        assert window.centralWidget().rect().contains(top)
        assert window.centralWidget().rect().contains(bottom)
    window.close()
    restored = Window(path)
    assert restored.size() == before
    restored.close()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native titlebar validation')
def test_windows_native_minimize_and_close_without_maximize(app, tmp_path):
    import subprocess
    from pathlib import Path
    # Other GUI tests use offscreen Qt. Run this one with an actual Windows HWND.
    script = '''
import sys, ctypes
from ctypes import wintypes
from pathlib import Path
from PySide6.QtWidgets import QApplication
from main import Window
app = QApplication([])
window = Window(Path(sys.argv[1]))
window.show()
app.processEvents()
user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
hwnd = wintypes.HWND(int(window.winId()))
style = user32.GetWindowLongW(hwnd, -16)
assert style & 0x00020000  # WS_MINIMIZEBOX
assert not style & 0x00010000  # WS_MAXIMIZEBOX
assert not style & 0x00040000  # WS_THICKFRAME / user resizing
before = window.size()
window.resize(1600, 1000)
app.processEvents()
assert window.size() == before
window.showMinimized()
app.processEvents()
assert window.isMinimized()
window.showNormal()
app.processEvents()
window.close()
assert not window.isVisible()
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'queue.json')],
                            cwd=Path(main.__file__).parent, env={**os.environ, 'QT_QPA_PLATFORM': 'windows'},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_retry_without_failures_never_starts_pending_items(app, tmp_path, monkeypatch):
    window = Window(tmp_path / 'queue.json')
    window.inspected({'id': 'pending', 'title': 'Pendiente'})
    monkeypatch.setattr(window, 'launch', lambda *args: pytest.fail('Must not start a download'))
    assert not window.retry.isEnabled()
    cell = window.table.item(0, 2)
    window.retry_failed()
    assert not window.running and window.worker is None
    assert window.items[0]['status'] == 'pending'
    assert window.table.item(0, 2) is cell
    assert 'No hay descargas fallidas' in window.status.text()
    window.close()


def test_retry_only_selected_failed_preserves_pending_and_completed(app, tmp_path, monkeypatch):
    script = '''import sys
from pathlib import Path
name = sys.argv[-1].rsplit('=', 1)[-1]
p = Path(sys.argv[sys.argv.index('-P') + 1]) / (name + '.mp3')
p.write_bytes(b'demo')
print('DF_FILE:' + str(p))
'''
    monkeypatch.setattr(main, 'engine_command', lambda: [sys.executable, '-c', script])
    monkeypatch.setattr(main.shutil, 'which', lambda name: 'mock-ffmpeg')
    window = Window(tmp_path / 'queue.json')
    window.folder.setText(str(tmp_path))
    window.inspected({'_type':'playlist','entries':[{'id':str(i),'title':str(i)} for i in range(5)]})
    for item, state in zip(window.items, ['pending','failed','done','failed','failed']):
        item['status'] = state
    window.items[3]['selected'] = False
    window.render()
    cell = window.title_cells[1]
    assert window.retry.isEnabled()
    window.retry_failed()
    window.retry_failed()  # A second call while running must not replace the worker.
    wait_for(app, lambda: not window.running and window.worker is None)
    assert [i['status'] for i in window.items] == ['pending','done','done','failed','done']
    assert not window.retry.isEnabled()
    assert window.title_cells[1] is cell
    assert not (tmp_path/'0.mp3').exists()
    assert not (tmp_path/'2.mp3').exists()
    assert not (tmp_path/'3.mp3').exists()
    window.close()


def test_fixed_window_rejects_maximize_and_adapts_to_new_screen(app, tmp_path):
    from PySide6.QtCore import QObject, Signal, QRect, QSize
    class Screen(QObject):
        availableGeometryChanged = Signal(QRect)
        def __init__(self, area):
            super().__init__()
            self.area = area
        def availableGeometry(self):
            return self.area
    window = Window(tmp_path / 'queue.json')
    window.show()
    app.processEvents()
    before = window.size()
    window.showMaximized()
    app.processEvents()
    assert not window.isMaximized() and window.size() == before
    window.showFullScreen()
    app.processEvents()
    assert not window.isFullScreen() and window.size() == before
    small = Screen(QRect(0,0,1366,720))
    big = Screen(QRect(1366,0,1920,1080))
    window.adapt_to_screen(small)
    assert window.size() == QSize(940,670)
    assert window.minimumSize() == window.maximumSize() == window.size()
    window.adapt_to_screen(big)
    assert window.size() == QSize(940,760)
    assert window.minimumSize() == window.maximumSize() == window.size()
    small.availableGeometryChanged.emit(QRect(0,0,900,700))
    assert window.size() == QSize(940,760)  # The previous monitor is disconnected.
    window.showMinimized()
    app.processEvents()
    assert window.isMinimized()
    window.showNormal()
    window.close()


def test_callback_exception_is_logged_and_window_survives(app, tmp_path):
    import json, subprocess
    from pathlib import Path
    script = '''
from pathlib import Path
import sys, json
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from main import Window
from diagnostics import install_diagnostics
app=QApplication([])
folder=Path(sys.argv[1])
window=Window(folder/'queue.json')
install_diagnostics(window, folder)
window.inspected({'id':'a','title':'Guardada'})
window.show()
def fail():
    raise RuntimeError('simulated callback exception')
QTimer.singleShot(0, fail)
def verify():
    assert window.isVisible()
    assert not window.running
    assert 'La cola se conservó' in window.status.text()
    assert 'simulated callback exception' in (folder/'errors.log').read_text()
    assert json.loads((folder/'queue.json').read_text())['items'][0]['title']=='Guardada'
    print('RECOVERY_OK', flush=True)
    app.quit()
QTimer.singleShot(30, verify)
app.exec()
'''
    result = subprocess.run([sys.executable,'-c',script,str(tmp_path)],cwd=Path(main.__file__).parent,
                            env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},capture_output=True,text=True,timeout=20)
    assert result.returncode == 0, result.stderr
    assert 'RECOVERY_OK' in result.stdout


def test_native_accessibility_sort_selection_and_list_replacement_survive(app, tmp_path):
    import subprocess
    from pathlib import Path
    script = '''
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QAccessible
from PySide6.QtCore import Qt, QEvent
from main import Window
app=QApplication([])
window=Window(Path(sys.argv[1]))
entries=[{'id':str(i),'title':f'Tema {100-i}'} for i in range(100)]
window.inspected({'_type':'playlist','entries':entries})
window.show()
app.processEvents()
QAccessible.setActive(True)
for n in range(12):
    iface=QAccessible.queryAccessibleInterface(window.table)
    children=[iface.child(i) for i in range(iface.childCount())]
    for child in children:
        if child: child.text(QAccessible.Name)
    window.table.sortItems(2, Qt.AscendingOrder if n%2 else Qt.DescendingOrder)
    window.select_all(n%2==0)
    window.search.setText('Tema 2' if n%2 else '')
    window.range_input.setText('2, 10-12')
    window.choose_range()
    app.processEvents()
    assert sum(i['selected'] for i in window.items)==4
window.inspected({'_type':'playlist','entries':entries[:20]})
app.sendPostedEvents(None, QEvent.DeferredDelete)
app.processEvents()
assert window.table.rowCount()==20
window.close()
'''
    platform = 'cocoa' if sys.platform=='darwin' else 'windows' if sys.platform=='win32' else 'offscreen'
    result = subprocess.run([sys.executable,'-c',script,str(tmp_path/'queue.json')],
                            cwd=Path(main.__file__).parent,env={**os.environ,'QT_QPA_PLATFORM':platform},
                            capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr


def test_header_clicks_toggle_applied_order(app, tmp_path):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint
    window=Window(tmp_path/'queue.json')
    window.inspected({'_type':'playlist','entries':[{'id':'z','title':'Zorro'},{'id':'a','title':'Árbol'}]})
    window.show(); app.processEvents()
    header=window.table.horizontalHeader()
    point=QPoint(header.sectionViewportPosition(2)+25, header.height()//2)
    QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=point)
    assert window.table.item(0,2).text()=='Árbol'
    QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=point)
    assert window.table.item(0,2).text()=='Zorro'
    QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=point)
    assert window.table.item(0,2).text()=='Árbol'
    window.close()
