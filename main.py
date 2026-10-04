import sys

# A separate child process runs downloads so cancellation never freezes the window.
if '--engine' in sys.argv:
    # Keep names and the parent/child protocol identical on every Windows locale.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    import yt_dlp
    yt_dlp.main(sys.argv[sys.argv.index('--engine') + 1:])
    raise SystemExit

if '--self-check' in sys.argv:
    import json
    from core import dependency_report
    report = dependency_report()
    print(json.dumps(report))
    raise SystemExit(0 if all(v == 'OK' for v in report.values()) else 1)

if getattr(sys, 'frozen', False) and sys.platform == 'win32':
    import ctypes
    ctypes.windll.kernel32.FreeConsole()

import json
import os
import shutil
import subprocess
import signal
import threading
import time
import queue
import errno
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt, QUrl, QSize, QLockFile, QCollator, QLocale, QEvent
from PySide6.QtGui import QDesktopServices, QColor, QFont, QIcon
from theme import apply_theme, action_icon, FriendlyComboBox, SelectionCheckBox, SelectionItemDelegate, brand_icon, ElidedLabel, StableTableWidget
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QFileDialog, QMessageBox, QAbstractItemView,
)
from core import (youtube_url, state_directory, save_state, load_state,
                  engine_command, download_arguments, binary_directory)
from core import finish_download, music_title
from library import DownloadLibrary, video_id
import sqlite3
from limits import (MAX_PLAYLIST_ITEMS, MAX_SCAN_ITEMS, MAX_OUTPUT_BYTES, MAX_LINE_BYTES, METADATA_TIMEOUT,
                    DOWNLOAD_TIMEOUT, INACTIVITY_TIMEOUT, CONVERSION_INACTIVITY_TIMEOUT,
                    MIN_FREE_BYTES, MAX_CONSECUTIVE_FAILURES, playlist_items)


class Engine(QThread):
    progress = Signal(int)
    result = Signal(object)
    problem = Signal(str)
    activity = Signal(str)

    def __init__(self, args, metadata=False, timeout=None, inactivity_timeout=None):
        super().__init__()
        self.args, self.metadata = args, metadata
        self.process = None
        self.streaming_metadata = metadata and '--dump-json' in args
        self.library_folder = None
        self.existing_items = []
        self.desired_format = 'MP3'
        self._batch_complete = False
        self.index_warning = ''
        self.stopped = False
        self.last_progress = -1
        self.download_info = {}
        self.failure_reason = ''
        self.fatal = False
        self.timeout = timeout if timeout is not None else METADATA_TIMEOUT if metadata else DOWNLOAD_TIMEOUT
        self.inactivity_timeout = inactivity_timeout if inactivity_timeout is not None else INACTIVITY_TIMEOUT
        self._kill_lock = threading.Lock()
        self._stop_started = None

    def stop(self):
        self.stopped = True
        if self._stop_started is None:
            self._stop_started = time.monotonic()
        if self.process:
            threading.Thread(target=self._stop_process_tree, daemon=True).start()

    def _stop_process_tree(self):
        if not self._kill_lock.acquire(blocking=False):
            return
        try:
            process = self.process
            if process is None:
                return
            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, timeout=10,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        finally:
            self._kill_lock.release()

    def _read_output(self, chunks, finished):
        # Fixed chunks and a bounded queue avoid unbounded JSON/log memory.
        try:
            while not finished.is_set():
                chunk = self.process.stdout.read1(65536)
                if not chunk:
                    break
                while not finished.is_set():
                    try:
                        chunks.put(chunk, timeout=.1)
                        break
                    except queue.Full:
                        pass
        except OSError as exc:
            if not finished.is_set():
                try:
                    chunks.put(exc, timeout=.1)
                except queue.Full:
                    pass
        finally:
            try:
                self.process.stdout.close()
            except OSError:
                pass
            finished.set()

    def run(self):
        finished = threading.Event()
        reader = None
        library = None
        prepared, prepared_ids, scanned, skipped = [], set(), 0, 0
        last_status = time.monotonic()
        try:
            if self.streaming_metadata:
                library = DownloadLibrary(self.library_folder)
                library.seed(self.existing_items)
            if not self.metadata and '-P' in self.args:
                folder = Path(self.args[self.args.index('-P') + 1])
                folder.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(folder).free < MIN_FREE_BYTES:
                    raise OSError(errno.ENOSPC, 'No hay espacio libre suficiente para empezar la descarga.')
            kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
            env = os.environ.copy()
            env['PYTHONUTF8'] = '1'
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PATH'] = str(binary_directory()) + os.pathsep + env.get('PATH', '')
            self.process = subprocess.Popen(engine_command() + self.args, env=env, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, **kwargs)
            if self.stopped:
                self.stop()
            chunks = queue.Queue(maxsize=32)
            reader = threading.Thread(target=self._read_output, args=(chunks, finished), daemon=True)
            reader.start()
            started = last_activity = time.monotonic()
            metadata_size, metadata_payload, errors, output_file = 0, None, [], ''
            buffer = bytearray()
            conversion = False
            def consume(raw):
                nonlocal metadata_payload, output_file, conversion, scanned, skipped, last_status
                line = raw.decode('utf-8', errors='replace').strip()
                if self.streaming_metadata:
                    if not line.startswith('{'):
                        if 'ERROR:' in line:
                            errors.append(line[:2000])
                            del errors[:-3]
                        return
                    entry = json.loads(line)
                    item = playlist_items(entry)[0]
                    scanned += 1
                    identity = entry['id']
                    if library.contains(identity, self.desired_format) or identity in prepared_ids:
                        skipped += 1
                    else:
                        prepared.append({'id':identity, 'title':item['title']})
                        prepared_ids.add(identity)
                    if time.monotonic() - last_status >= .5:
                        self.activity.emit(f'Preparados: {len(prepared)} de {MAX_PLAYLIST_ITEMS}. Ya en la carpeta: {skipped}.')
                        last_status = time.monotonic()
                    if len(prepared) >= MAX_PLAYLIST_ITEMS or scanned >= MAX_SCAN_ITEMS:
                        self._batch_complete = True
                        self.stop()
                elif self.metadata:
                    if line.startswith('{'):
                        metadata_payload = line
                elif line.startswith('DF_PROGRESS:'):
                    try:
                        percent = max(0, min(100, int(float(line.split(':', 1)[1].strip().rstrip('%')))))
                        if percent != self.last_progress:
                            self.last_progress = percent
                            self.progress.emit(percent)
                    except (ValueError, OverflowError):
                        pass
                elif line.startswith('DF_FILE:'):
                    output_file = line.split(':', 1)[1]
                elif line.startswith('DF_META:'):
                    try:
                        info = json.loads(line.split(':', 1)[1])
                        if isinstance(info, dict):
                            self.download_info = {key: value[:500] for key, value in info.items()
                                                  if key in ('id', 'title', 'track', 'artist', 'album') and isinstance(value, str)}
                            if isinstance(info.get('artists'), list):
                                self.download_info['artists'] = [a[:200] for a in info['artists'][:20] if isinstance(a, str)]
                    except ValueError:
                        pass
                elif line.startswith(('[ExtractAudio]', '[Merger]', '[VideoConvertor]', '[VideoRemuxer]', '[Metadata]')):
                    conversion = True
                elif 'ERROR:' in line:
                    errors.append(line[:2000])
                    del errors[:-3]
            while not self._batch_complete:
                now = time.monotonic()
                idle_limit = CONVERSION_INACTIVITY_TIMEOUT if conversion else self.inactivity_timeout
                if not self.stopped and (now - started > self.timeout or now - last_activity > idle_limit):
                    self.failure_reason = 'La operación tardó demasiado o dejó de responder. Puedes reintentarla.'
                    self.stop()
                if self.stopped and self._stop_started and now - self._stop_started > 12:
                    break
                try:
                    chunk = chunks.get(timeout=.1)
                except queue.Empty:
                    if finished.is_set() and chunks.empty():
                        break
                    continue
                if isinstance(chunk, Exception):
                    raise chunk
                last_activity = now
                metadata_size += len(chunk)
                if self.metadata and not self.streaming_metadata and metadata_size > MAX_OUTPUT_BYTES:
                    raise ValueError('La respuesta de YouTube es demasiado grande. Usa una playlist más pequeña.')
                buffer.extend(chunk)
                limit = MAX_OUTPUT_BYTES if self.metadata and not self.streaming_metadata else MAX_LINE_BYTES
                if len(buffer) > limit:
                    raise ValueError('El motor devolvió una respuesta demasiado grande.')
                while b'\n' in buffer:
                    line, _, rest = buffer.partition(b'\n')
                    buffer = bytearray(rest)
                    consume(line)
                    if self._batch_complete:
                        break
            if buffer and not self.stopped:
                consume(buffer)
            try:
                code = self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.failure_reason = 'El motor no terminó a tiempo. Puedes volver a intentarlo.'
                self.stop()
                code = -1
            if self.streaming_metadata and (self._batch_complete or not self.stopped and not code):
                self.result.emit({'_type':'playlist', 'entries':prepared, 'batch_prepared':True,
                                  'scanned':scanned, 'skipped':skipped,
                                  'scan_limit_reached':scanned >= MAX_SCAN_ITEMS})
            elif self.stopped:
                self.problem.emit(self.failure_reason or 'Descarga detenida. Puedes continuar cuando quieras.')
            elif code:
                self.problem.emit('\n'.join(errors[-3:]) or 'No se pudo completar. Comprueba tu conexión e inténtalo de nuevo.')
            elif self.metadata:
                if not metadata_payload:
                    raise ValueError('YouTube no devolvió información del enlace.')
                info = json.loads(metadata_payload)
                playlist_items(info)  # Validate bounds before passing data to the GUI.
                self.result.emit(info)
            elif not output_file or not Path(output_file).is_file():
                self.problem.emit('No se encontró el archivo terminado. Vuelve a intentar la descarga.')
            else:
                filename = finish_download(output_file, self.download_info, '-x' in self.args)
                try:
                    index = DownloadLibrary(Path(filename).parent)
                    try:
                        identity = self.download_info.get('id') or (video_id(self.args[-1]) if self.args else '')
                        index.remember(identity, filename)
                    finally:
                        index.close()
                except (OSError, sqlite3.Error, ValueError) as exc:
                    self.index_warning = 'El archivo se descargó, pero no se pudo registrar en la carpeta. La cola se ha pausado: ' + str(exc)
                self.result.emit(filename)
        except Exception as exc:
            self.fatal = isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EACCES, errno.EROFS, errno.ENOENT)
            if isinstance(exc, sqlite3.Error):
                message = 'No se pudo leer o guardar el índice de esta carpeta. Comprueba sus permisos o elige otra ubicación.'
            elif isinstance(exc, PermissionError):
                message = 'No hay permiso para guardar en esa carpeta. Elige otra ubicación.'
            elif isinstance(exc, FileNotFoundError):
                message = 'Falta un componente o la carpeta dejó de estar disponible. Reinstala la app o elige otra carpeta.'
            else:
                message = str(exc) or 'No se pudo completar la operación.'
            self.problem.emit(message)
        finally:
            finished.set()
            if self.process and self.process.poll() is None:
                self._stop_process_tree()
            if reader:
                reader.join(timeout=1)
            if library:
                library.close()


class TitleItem(QTableWidgetItem):
    collator = QCollator(QLocale('es'))
    collator.setCaseSensitivity(Qt.CaseInsensitive)
    collator.setNumericMode(True)

    def __lt__(self, other):
        return self.collator.compare(self.text(), other.text()) < 0


class Window(QMainWindow):
    def __init__(self, state_path=None):
        super().__init__()
        self.path = state_path or state_directory() / 'queue.json'
        try:
            self.state = load_state(self.path)
        except (ValueError, OSError):
            self.state = {}
        self.source_url = self.state.get('source_url') or self.state.get('url', '')
        self.items = self.state.get('items', [])
        self._legacy_oversized_queue = len(self.items) > MAX_PLAYLIST_ITEMS
        self.worker = None
        self.running = False
        self.pause_requested = False
        self.pause_message = ''
        self.consecutive_failures = 0
        self.current = None
        self.retry_indices = None
        self._screen = None
        self._screen_connected = False
        self._recovering_error = False
        self.setWindowTitle('Bajada — Videos y música')
        self.setWindowIcon(brand_icon())
        self.setWindowFlags(Qt.Window | Qt.MSWindowsFixedSizeDialogHint | Qt.CustomizeWindowHint | Qt.WindowTitleHint |
                            Qt.WindowSystemMenuHint | Qt.WindowMinimizeButtonHint |
                            Qt.WindowCloseButtonHint)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        heading = QLabel('Bajada')
        heading.setObjectName('heading')
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(brand_icon().pixmap(48, 48))
        logo.setFixedSize(48, 48)
        header.addWidget(logo)
        header.addSpacing(12)
        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        header_text.addWidget(heading)
        subtitle = QLabel('Descarga videos y música de YouTube')
        subtitle.setObjectName('subtitle')
        header_text.addWidget(subtitle)
        header.addLayout(header_text, 1)
        layout.addLayout(header)
        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText('Pega un enlace de YouTube')
        self.url.setToolTip('Copia un enlace y pulsa Procesar; también puedes pegarlo en este campo.')
        self.analyze = QPushButton('Procesar')
        self.analyze.setObjectName('process')
        self.analyze.setFixedWidth(132)
        self.analyze.setToolTip('Lee el enlace del campo; si está vacío, usa el enlace que copiaste.')
        self.analyze.clicked.connect(self.inspect)
        self.url.returnPressed.connect(self.inspect)
        row.addWidget(self.url, 1)
        row.addWidget(self.analyze)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.mode = FriendlyComboBox()
        self.mode.addItems(['Video', 'Solo audio'])
        self.format = FriendlyComboBox()
        self.quality = FriendlyComboBox()
        self.quality.addItems(['720p', '1080p', '480p', 'Mejor disponible'])
        for label, control, width in [('Tipo', self.mode, 180), ('Formato', self.format, 150), ('Calidad', self.quality, 260)]:
            field_widget = QWidget()
            field_widget.setFixedWidth(width)
            field = QVBoxLayout(field_widget)
            field.setContentsMargins(0, 0, 0, 0)
            field.setSpacing(4)
            label_widget = QLabel(label)
            label_widget.setObjectName('fieldLabel')
            field.addWidget(label_widget)
            field.addWidget(control)
            row.addWidget(field_widget)
            if control is self.quality:
                self.quality_container = field_widget
        row.addStretch()
        layout.addLayout(row)
        self.mode.currentIndexChanged.connect(self.formats)
        self.format.currentTextChanged.connect(self.update_quality)
        self.formats()
        settings = self.state.get('settings', {})
        self.mode.setCurrentIndex(1)
        self.format.setCurrentText('MP3')
        self.quality.setCurrentIndex(1)
        list_header = QHBoxLayout()
        list_label = QLabel('Tu lista de descargas')
        list_label.setObjectName('sectionTitle')
        self.summary = QLabel()
        self.summary.setObjectName('summary')
        self.search = QLineEdit()
        self.search.setMaximumWidth(250)
        self.search.setPlaceholderText('Buscar título o número…')
        self.search.setClearButtonEnabled(True)
        self.search.addAction(action_icon('search'), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self.filter_rows)
        list_header.addWidget(list_label)
        list_header.addWidget(self.search, 1)
        list_header.addStretch()
        list_header.addWidget(self.summary)
        layout.addLayout(list_header)
        self.status_cells = {}
        self.title_cells = {}
        self.table = self.create_table()
        self._rendered_items = None
        self.table_layout = layout
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.select_all_check = SelectionCheckBox('Seleccionar todos')
        self.select_all_check.setMinimumWidth(180)
        self.select_all_check.setTristate(True)
        self.select_all_check.clicked.connect(lambda checked: self.select_all(checked))
        self.select_all_check.setToolTip('Marca o desmarca la lista, incluso durante la descarga. Desmarcar omite los pendientes; el archivo actual termina. Un guion indica una selección parcial.')
        self.range_input = QLineEdit()
        self.range_input.setFixedWidth(210)
        self.range_input.setPlaceholderText('Ejemplo: 1-50, 80')
        self.range_input.setToolTip('Los números corresponden al orden original de la playlist, aunque ordenes por título.')
        self.range_button = QPushButton('Aplicar rango')
        self.range_button.clicked.connect(self.choose_range)
        self.range_input.returnPressed.connect(self.choose_range)
        row.addWidget(self.select_all_check)
        row.addWidget(self.range_input)
        row.addWidget(self.range_button)
        row.addStretch()
        layout.addLayout(row)
        self.folder = QLineEdit(settings.get('folder', str(Path.home() / 'Videos' / 'Bajada')))
        self.folder.setMaximumWidth(590)
        self.folder.setToolTip(self.folder.text())
        self.folder.textChanged.connect(self.folder.setToolTip)
        self.folder.setReadOnly(True)
        self.change_folder = QPushButton('Cambiar carpeta')
        self.change_folder.clicked.connect(self.choose_folder)
        row = QHBoxLayout()
        row.addWidget(QLabel('Guardar en:'))
        row.addWidget(self.folder, 1)
        row.addWidget(self.change_folder)
        row.addStretch()
        layout.addLayout(row)
        self.download = QPushButton('Descargar seleccionados')
        self.download.setObjectName('primary')
        self.download.clicked.connect(self.start_queue)
        self.download_row = QHBoxLayout()
        self.download_row.addWidget(self.download, 1)
        layout.addLayout(self.download_row)
        self.status = ElidedLabel('Copia un enlace y pulsa «Procesar».' if not self.items else
                                  f'Cola anterior conservada. Límite actual: {MAX_PLAYLIST_ITEMS} por playlist.' if self._legacy_oversized_queue else
                                  'Cola recuperada. Puedes continuar.')
        self.status.setFixedHeight(24)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.pause = QPushButton('Pausar cola')
        self.pause.setToolTip('Termina el archivo actual y espera antes de empezar el siguiente.')
        self.pause.clicked.connect(self.pause_queue)
        self.cancel = QPushButton('Detener descarga')
        self.cancel.setToolTip('Interrumpe el archivo actual y detiene la cola. Conserva los archivos parciales para intentar continuar.')
        self.cancel.clicked.connect(self.cancel_queue)
        self.retry = QPushButton('Reintentar fallidos')
        self.retry.setToolTip('Reintenta solo los fallidos seleccionados; conserva los archivos completados.')
        self.retry.clicked.connect(self.retry_failed)
        self.open_folder = QPushButton('Abrir carpeta')
        self.open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder.text())))
        footer = QHBoxLayout()
        for button in (self.pause, self.cancel, self.retry, self.open_folder):
            footer.addWidget(button, 1)
        layout.addLayout(footer)
        self.pause.setEnabled(False)
        self.cancel.setEnabled(False)
        self.render()
        for button, symbol in [(self.pause, 'pause'),
                               (self.cancel, 'stop'), (self.retry, 'retry'),
                               (self.open_folder, 'folder'), (self.change_folder, 'folder')]:
            button.setIcon(action_icon(symbol, '#315c8e'))
            button.setIconSize(QSize(20, 20))
        self.status.setObjectName('status')
        self.mode.currentIndexChanged.connect(self.download_label)
        self.download_label()
        apply_theme(self)
        # One medium size per screen; old saved sizes cannot enlarge the app.
        self.adapt_to_screen(self.screen())

    def create_table(self):
        table = StableTableWidget(0, 4, self)
        table.setItemDelegateForColumn(0, SelectionItemDelegate(table))
        table.setMinimumHeight(140)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setHorizontalHeaderLabels(['Elegir', 'Nº', 'Título', 'Estado'])
        for column in (1, 2):
            table.horizontalHeaderItem(column).setToolTip('Pulsa para ordenar; pulsa otra vez para invertir el orden.')
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        table.horizontalHeader().setSortIndicator(1, Qt.AscendingOrder)
        table.horizontalHeader().setSortIndicatorShown(True)
        table.orderChanged.connect(self.filter_rows)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        table.verticalHeader().setDefaultSectionSize(42)
        table.setColumnWidth(0, 65)
        table.setColumnWidth(1, 60)
        table.setColumnWidth(3, 145)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.itemChanged.connect(self.selection_changed)
        return table

    def showEvent(self, event):
        super().showEvent(event)
        if not self._screen_connected and self.windowHandle():
            self.windowHandle().screenChanged.connect(self.adapt_to_screen)
            self._screen_connected = True
            self.adapt_to_screen(self.windowHandle().screen())

    def adapt_to_screen(self, screen):
        if screen is None:
            return
        if screen is not self._screen:
            if self._screen is not None:
                try:
                    self._screen.availableGeometryChanged.disconnect(self.screen_geometry_changed)
                except (RuntimeError, TypeError):
                    pass
            self._screen = screen
            screen.availableGeometryChanged.connect(self.screen_geometry_changed)
        self.fit_to_screen(screen.availableGeometry())

    def screen_geometry_changed(self, area):
        self.fit_to_screen(area)

    def fit_to_screen(self, area):
        self.setFixedSize(max(1, min(940, area.width() - 30)),
                          max(1, min(760, area.height() - 50)))
        if self.isVisible():
            frame = self.frameGeometry()
            x = max(area.left(), min(frame.left(), area.right() - frame.width() + 1))
            y = max(area.top(), min(frame.top(), area.bottom() - frame.height() + 1))
            self.move(x, y)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            forbidden = Qt.WindowMaximized | Qt.WindowFullScreen
            if self.windowState() & forbidden:
                self.setWindowState(self.windowState() & ~forbidden)

    def formats(self):
        audio = self.mode.currentIndex() == 1
        self.format.blockSignals(True)
        self.format.clear()
        self.format.addItems(['MP3', 'M4A', 'AAC', 'FLAC'] if audio else ['MP4', 'MKV', 'WebM', 'MOV', 'AVI'])
        self.format.blockSignals(False)
        self.update_quality()

    def update_quality(self):
        previous = self.quality.currentData()
        self.quality.clear()
        if self.mode.currentIndex() == 1:
            if self.format.currentText() == 'FLAC':
                self.quality.addItem('Original (FLAC sin pérdida)', 'lossless')
            else:
                for label, value in [('Alta (256 kbps)', '256kbps'), ('Media (192 kbps)', '192kbps'), ('Baja (128 kbps)', '128kbps')]:
                    self.quality.addItem(label, value)
        else:
            for label, value in [('Alta (1080p)', '1080p'), ('Media (720p)', '720p'), ('Baja (480p)', '480p')]:
                self.quality.addItem(label, value)
        index = self.quality.findData(previous)
        self.quality.setCurrentIndex(index if index >= 0 else min(1, self.quality.count() - 1))
        self.quality_container.setVisible(True)
        self.quality.setEnabled(True)
        self.quality.setToolTip('La calidad de la fuente limita el resultado. FLAC no recupera información perdida en YouTube.')
        self.format.setToolTip('MOV y AVI pueden requerir conversión y tardar más.')

    def download_label(self):
        self.download.setText('Descargar seleccionados')
        self.download.setToolTip('Descarga el audio de los elementos elegidos.' if self.mode.currentIndex() == 1
                                 else 'Descarga los videos elegidos.')

    def settings(self):
        return {'mode': 'audio' if self.mode.currentIndex() else 'video',
                'format': self.format.currentText(), 'quality': self.quality.currentData(),
                'folder': self.folder.text()}

    def persist(self):
        try:
            save_state(self.path, {'url': self.url.text(), 'source_url': self.source_url, 'settings': self.settings(), 'items': self.items,
                                  'window_size': [self.width(), self.height()]})
        except (OSError, ValueError):
            if self.running:
                self.pause_requested = True
            self.status.setText('No se pudo guardar la cola. Comprueba el espacio y los permisos; la cola se pausará.')

    def render(self):
        # Selection/range/retry keep the same cells. Rebuilding a visible sorted
        # QTableWidget invalidated Qt's native accessibility cache and crashed.
        if self._rendered_items is not None and len(self._rendered_items) == len(self.items) and all(
                previous is current for previous, current in zip(self._rendered_items, self.items)):
            self.table.blockSignals(True)
            try:
                for row in range(self.table.rowCount()):
                    cell = self.table.item(row, 0)
                    item = self.items[cell.data(Qt.UserRole)]
                    cell.setCheckState(Qt.Checked if item.get('selected', True) else Qt.Unchecked)
                for index, item in enumerate(self.items):
                    self.set_status_cell(self.status_cells[index], item)
            finally:
                self.table.blockSignals(False)
            self.filter_rows()
            self.refresh_summary()
            return
        old_table = self.table if self._rendered_items is not None else None
        header = self.table.horizontalHeader()
        column, order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        if old_table is not None:
            self.table = self.create_table()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        self.status_cells = {}
        self.title_cells = {}
        for index, item in enumerate(self.items):
            checkbox = QTableWidgetItem()
            checkbox.setData(Qt.UserRole, index)
            checkbox.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            checkbox.setToolTip('Desmarcar omite este elemento si aún está pendiente. No cancela el archivo que ya se está descargando.')
            checkbox.setCheckState(Qt.Checked if item.get('selected', True) else Qt.Unchecked)
            number = QTableWidgetItem()
            number.setData(Qt.DisplayRole, index + 1)
            number.setTextAlignment(Qt.AlignCenter)
            title = TitleItem(' '.join(item['title'].split()))
            title.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            title.setToolTip(item['title'])
            status = QTableWidgetItem()
            status.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            font = self.table.font()
            font.setPixelSize(16)
            font.setWeight(QFont.DemiBold)
            status.setFont(font)
            self.set_status_cell(status, item)
            for col, cell in enumerate((checkbox, number, title, status)):
                self.table.setItem(index, col, cell)
            self.status_cells[index] = status
            self.title_cells[index] = title
            self.table.setRowHeight(index, 42)
        self.table.sortItems(column, order)
        self.table.blockSignals(False)
        self._rendered_items = list(self.items)
        if old_table is not None:
            self.table_layout.replaceWidget(old_table, self.table)
            old_table.hide()
            old_table.orderChanged.disconnect(self.filter_rows)
            old_table.itemChanged.disconnect(self.selection_changed)
            old_table.deleteLater()
            self.table.show()
        self.filter_rows()
        self.refresh_summary()

    def set_status_cell(self, cell, item):
        labels = {'pending': 'Pendiente', 'done': 'Completado', 'failed': 'Fallido', 'downloading': 'Descargando'}
        colors = {'pending': '#657387', 'done': '#13734e', 'failed': '#b33b38', 'downloading': '#176bd1'}
        cell.setText(labels[item['status']])
        cell.setForeground(QColor(colors[item['status']]))
        cell.setToolTip(item.get('error', ''))

    def filter_rows(self):
        import unicodedata
        def normalized(value):
            return ''.join(ch for ch in unicodedata.normalize('NFD', value.casefold())
                           if unicodedata.category(ch) != 'Mn')
        query = normalized(self.search.text().strip())
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            if cell is None:
                continue
            index = cell.data(Qt.UserRole)
            title = normalized(self.items[index]['title'])
            self.table.setRowHidden(row, bool(query) and query not in title and query != str(index + 1))

    def refresh_summary(self):
        selected = sum(i.get('selected', True) for i in self.items)
        completed = sum(i['status'] == 'done' for i in self.items)
        self.summary.setText(f'{selected} elegidos  •  {completed} completados' if self.items else 'Sin videos todavía')
        self.select_all_check.blockSignals(True)
        if self.items and selected == len(self.items):
            state = Qt.Checked
        elif selected:
            state = Qt.PartiallyChecked
        else:
            state = Qt.Unchecked
        self.select_all_check.setCheckState(state)
        self.select_all_check.blockSignals(False)
        if hasattr(self, 'retry'):
            eligible = sum(i['status'] == 'failed' and i.get('selected', True) for i in self.items)
            self.retry.setEnabled(bool(eligible) and not self.running and self.worker is None)

    def update_current_row(self):
        if self.current is None:
            return
        index = next(i for i, item in enumerate(self.items) if item is self.current)
        self.table.blockSignals(True)
        title_changed = self.title_cells[index].text() != ' '.join(self.current['title'].split())
        self.title_cells[index].setText(' '.join(self.current['title'].split()))
        self.title_cells[index].setToolTip(self.current['title'])
        self.set_status_cell(self.status_cells[index], self.current)
        self.table.blockSignals(False)
        header = self.table.horizontalHeader()
        if title_changed and header.sortIndicatorSection() == 2:
            self.table.sortItems(2, header.sortIndicatorOrder())
        self.filter_rows()
        self.refresh_summary()

    def selection_changed(self, cell):
        if cell.column() == 0:
            index = cell.data(Qt.UserRole)
            self.items[index]['selected'] = cell.checkState() == Qt.Checked
            self.refresh_summary()
            self.persist()

    def select_all(self, selected):
        for item in self.items:
            item['selected'] = selected
        self.render()
        self.persist()

    def choose_range(self):
        try:
            indices = set()
            for part in self.range_input.text().split(','):
                bounds = [int(v.strip()) for v in part.split('-')]
                if len(bounds) not in (1, 2):
                    raise ValueError
                first, last = bounds[0], bounds[-1]
                if not 1 <= first <= last <= len(self.items):
                    raise ValueError
                indices.update(range(first - 1, last))
            for index, item in enumerate(self.items):
                item['selected'] = index in indices
            self.render()
            self.persist()
        except ValueError:
            QMessageBox.information(self, 'Elegir videos', 'Escribe números dentro de la lista, por ejemplo: 1-50, 80.')

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Dónde guardar', self.folder.text())
        if folder:
            self.folder.setText(folder)
            self.persist()

    def controls(self, busy):
        # Browsing and live selection stay usable; next_item reads selection afresh.
        for widget in [self.analyze, self.mode, self.format, self.change_folder, self.download, self.retry]:
            widget.setEnabled(not busy)
        for widget in (self.table, self.search, self.select_all_check, self.range_input, self.range_button, self.open_folder):
            widget.setEnabled(True)
        self.url.setEnabled(not busy or self.running)
        self.quality.setEnabled(not busy)
        self.pause.setEnabled(busy and self.running)
        self.cancel.setEnabled(busy)
        self.refresh_summary()

    def launch(self, args, success, failure, metadata=False):
        self.worker = Engine(args, metadata)
        if metadata:
            self.worker.library_folder = self.folder.text()
            self.worker.existing_items = [dict(item) for item in self.items]
            self.worker.desired_format = self.format.currentText()
        self.worker.activity.connect(self.status.setText)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.result.connect(success)
        self.worker.problem.connect(failure)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def worker_finished(self):
        # Keep the worker referenced until the thread has actually ended.
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        if self._recovering_error:
            self._recovering_error = False
            if self.current and self.current['status'] == 'downloading':
                self.current['status'] = 'pending'
                self.update_current_row()
            self.end_queue('Se produjo un error. La cola se conservó; puedes volver a intentarlo.')
        elif self.running:
            self.next_item()
        else:
            self.refresh_summary()

    def handle_unexpected_error(self):
        self.pause_requested = True
        self.running = False
        self._recovering_error = self.worker is not None
        if self.worker:
            self.worker.stop()
        elif self.current and self.current['status'] == 'downloading':
            self.current['status'] = 'pending'
            self.update_current_row()
        self.persist()
        self.controls(self.worker is not None)
        self.status.setText('Se produjo un error. La cola se conservó; puedes volver a intentarlo.')

    def inspect(self):
        if self.worker or self.running:
            return
        candidate = self.url.text().strip() or QApplication.clipboard().text().strip()
        try:
            url = youtube_url(candidate)
        except ValueError as exc:
            QMessageBox.information(self, 'Enlace', str(exc))
            return
        self.url.setText(url)
        if self.items and any(i['status'] != 'done' for i in self.items):
            if QMessageBox.question(self, 'Cambiar lista', 'Esto reemplazará la cola guardada. ¿Continuar?') != QMessageBox.Yes:
                return
        self.controls(True)
        self.status.setText('Leyendo la lista de YouTube… Una lista grande puede tardar.')
        self.progress.setRange(0, 0)
        self.launch(['--ignore-config', '--flat-playlist', '--lazy-playlist', '--dump-json', '--simulate', '--no-warnings', '--no-colors',
                     '--playlist-end', str(MAX_SCAN_ITEMS), '--extractor-retries', '2',
                     '--socket-timeout', '20', '--', url], self.inspected, self.inspect_failed, True)

    def inspected(self, info):
        try:
            new_items = playlist_items(info, allow_empty=info.get('batch_prepared') is True)
        except ValueError as exc:
            self.inspect_failed(str(exc))
            return
        if not new_items:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.status.setText(('Se alcanzó el límite de revisión de 200.000 elementos. ' if info.get('scan_limit_reached') else '') +
                                'No hay archivos nuevos en la parte revisada para este formato. La cola anterior se conserva.')
            self.controls(False)
            return
        self.source_url = self.url.text()
        self.items = new_items
        self._legacy_oversized_queue = False
        self.render()
        self.persist()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status.setText(f'{len(self.items)} preparados. {info.get("skipped", 0)} ya estaban en la carpeta. ' +
                            ('Se alcanzó el límite de revisión de 200.000 elementos.' if info.get("scan_limit_reached") else 'Vuelve a procesar el enlace para buscar el siguiente lote.'))
        self.controls(False)

    def inspect_failed(self, message):
        self.progress.setRange(0, 100)
        self.controls(False)
        self.status.setText(message[:500])
        self.show_error(message)

    def show_error(self, message):
        box = QMessageBox(self)
        box.setWindowTitle('No se pudo completar')
        box.setText(message[:1500])
        box.setDetailedText(message)
        self.error_box = box
        box.open()

    def start_queue(self, checked=False, retry_indices=None):
        if self.worker or self.running:
            return
        if self._legacy_oversized_queue:
            self.status.setText(f'Esta cola anterior tiene más de {MAX_PLAYLIST_ITEMS} elementos. Se conserva, pero debes procesar una playlist más pequeña para descargar.')
            return
        if retry_indices is None:
            ready = any(i.get('selected', True) and i['status'] == 'pending' for i in self.items)
        else:
            ready = any(i in retry_indices and item.get('selected', True) and item['status'] == 'failed'
                        for i, item in enumerate(self.items))
        if not ready:
            self.status.setText('No hay elementos pendientes seleccionados.' if retry_indices is None
                                else 'No hay descargas fallidas seleccionadas para reintentar.')
            return
        vendor = binary_directory()
        if not shutil.which('ffmpeg') and not (vendor / 'ffmpeg.exe').is_file():
            QMessageBox.information(self, 'Falta un componente', 'Esta copia no incluye FFmpeg. Usa el instalador completo para Windows.')
            return
        self.retry_indices = retry_indices
        if retry_indices is not None:
            for index in retry_indices:
                self.items[index]['status'] = 'pending'
                self.set_status_cell(self.status_cells[index], self.items[index])
        self.running = True
        self.pause_requested = False
        self.pause_message = ''
        self.consecutive_failures = 0
        self.controls(True)
        self.persist()
        self.next_item()

    def next_item(self):
        if self.pause_requested:
            self.end_queue(self.pause_message or 'Cola pausada. Pulsa Descargar para continuar.')
            return
        self.current = next((item for index, item in enumerate(self.items)
                             if item.get('selected', True) and item['status'] == 'pending'
                             and (self.retry_indices is None or index in self.retry_indices)), None)
        if self.current is None:
            done = sum(i['status'] == 'done' for i in self.items)
            failed = sum(i['status'] == 'failed' for i in self.items)
            self.end_queue(f'Cola terminada. Completados: {done}. Fallidos: {failed}.')
            return
        item = self.current
        # Each entry keeps its original target so resuming does not mix formats or destinations.
        item.setdefault('settings', self.settings())
        try:
            args = download_arguments(item, item['settings'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.end_queue(str(exc))
            return
        item['status'] = 'downloading'
        self.persist()
        self.update_current_row()
        self.progress.setValue(0)
        completed = sum(i['status'] == 'done' for i in self.items)
        self.status.setText(f'Completados: {completed} de {len(self.items)}. Descargando: {item["title"]}')
        self.launch(args, self.item_done, self.item_failed)

    def item_done(self, filename):
        info = self.worker.download_info if self.worker else {}
        name = music_title(info) if self.current.get('settings', {}).get('mode') == 'audio' else None
        if name:
            self.current.setdefault('original_title', self.current['title'])
            self.current['title'] = name
            self.current['music_metadata'] = info
        if self.worker and self.worker.index_warning:
            self.pause_requested = True
            self.pause_message = self.worker.index_warning
        self.consecutive_failures = 0
        self.current.update(status='done', file=filename, error='')
        self.persist()
        self.update_current_row()

    def item_failed(self, message):
        interrupted = self.worker.stopped and not self.worker.failure_reason
        self.current.update(status='pending' if interrupted else 'failed', error=message)
        if not interrupted:
            self.consecutive_failures += 1
            if self.worker.fatal or self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                self.pause_requested = True
                self.pause_message = ('Cola pausada: ' + message if self.worker.fatal else
                                      'Cola pausada tras 5 fallos seguidos. Comprueba la conexión y reintenta los fallidos.')
        self.persist()
        self.update_current_row()

    def pause_queue(self):
        self.pause_requested = True
        self.status.setText('La cola se pausará cuando termine el video actual.')
        self.pause.setEnabled(False)

    def cancel_queue(self):
        self.pause_requested = True
        if self.worker:
            self.worker.stop()
        self.status.setText('Deteniendo… Los archivos terminados se conservarán.')

    def retry_failed(self):
        if self.worker or self.running:
            return
        targets = {index for index, item in enumerate(self.items)
                   if item['status'] == 'failed' and item.get('selected', True)}
        if not targets:
            self.status.setText('No hay descargas fallidas seleccionadas para reintentar.')
            self.refresh_summary()
            return
        self.start_queue(retry_indices=targets)

    def end_queue(self, message):
        self.running = False
        self.retry_indices = None
        self.controls(False)
        self.status.setText(message)
        self.persist()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, 'Descarga en curso', 'Pulsa Detener descarga y espera a que termine antes de cerrar.')
            event.ignore()
            return
        self.persist()
        event.accept()


if __name__ == '__main__':
    from diagnostics import install_diagnostics
    install_diagnostics()
    app = QApplication(sys.argv)
    if '--smoke-test' in sys.argv:
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            window = Window(Path(folder) / 'queue.json')
            window.show()
            app.processEvents()
            window.close()
        raise SystemExit(0)
    lock = QLockFile(str(state_directory() / 'app.lock'))
    if not lock.tryLock(0):
        QMessageBox.information(None, 'Bajada', 'La aplicación ya está abierta. Busca su ventana para continuar.')
        raise SystemExit(0)
    window = Window()
    install_diagnostics(window)
    window.show()
    sys.exit(app.exec())
