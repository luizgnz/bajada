# Componentes incluidos

Bajada usa componentes independientes con sus propias licencias. Sus ejecutables y bibliotecas permanecen como archivos separados; no se exige una firma ni una comprobación de integridad al ejecutar una copia modificada. El inventario solo verifica el paquete al instalarlo o con --self-check.

- PySide6 / Qt 6.11.2: LGPLv3, GPLv3 y licencias comerciales, según sus componentes. Se usan Core, Gui y Widgets. Código: https://code.qt.io/cgit/pyside/pyside-setup.git/ y https://code.qt.io/cgit/qt/qtbase.git/ . Distribución de fuentes de Qt: https://download.qt.io/official_releases/qt/6.11/6.11.2/ . Las licencias LGPLv3 y GPLv3 se entregan en el paquete.
- yt-dlp: Unlicense; https://github.com/yt-dlp/yt-dlp . Dependencias adicionales conservan las licencias de sus distribuciones Python.
- FFmpeg: variante **LGPL compartida**, sin componentes GPL ni nonfree, del proveedor BtbN enlazado por ffmpeg.org. Código: https://github.com/FFmpeg/FFmpeg . Recetas y fuentes de dependencias: https://github.com/BtbN/FFmpeg-Builds . El paquete registra versión, configuración y revisión de las recetas; incluye los avisos del proveedor y los enlaces a fuentes de la revisión usada.
- Deno: MIT; https://github.com/denoland/deno . El paquete registra la versión exacta descargada y su enlace de fuentes.
- Python: PSF; https://www.python.org/ . PyInstaller: GPL con excepción para el ejecutable generado; https://pyinstaller.org/ . Los avisos disponibles se copian al directorio licenses.

Los enlaces de las versiones realmente empaquetadas se encuentran en vendor/component-sources.txt y vendor/FFMPEG-BUILD.txt de la copia instalada. El código de Bajada está disponible en el repositorio público, junto con los scripts para construir y modificar el paquete.
