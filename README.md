# Bajada

Aplicación sencilla en español para descargar videos, música y playlists de YouTube. Interfaz hecha en Python y PySide6; las descargas usan yt-dlp en un proceso separado.

## Windows

Descarga **Bajada-Setup.exe** desde [Releases](https://github.com/luizgnz/bajada/releases). Windows 10 (2004 o posterior) y Windows 11, de 64 bits.

El instalador incluye Python, Qt, yt-dlp, FFmpeg, FFprobe y Deno: no hace falta instalar herramientas aparte. La versión de prueba no tiene firma digital; Windows puede mostrar «editor desconocido».

## Uso

1. Elige la carpeta y el formato. Al abrir, viene seleccionado audio MP3, calidad media de 192 kbps.
2. Pega el enlace y pulsa **Procesar**.
3. Busca, ordena haciendo clic en los encabezados y selecciona los elementos. El check **Seleccionar todos** también permite desmarcarlos.
4. Pulsa **Descargar seleccionados**.

Audio: MP3, M4A, AAC y FLAC. Video: MP4, MKV, WebM, MOV y AVI. Convertir a MOV/AVI puede tardar más. La calidad elegida es un máximo; la fuente determina la calidad realmente disponible. FLAC conserva el audio original sin pérdidas adicionales, pero no mejora una fuente comprimida.

**Pausar cola** termina el elemento actual y deja los siguientes pendientes. **Detener descarga** cancela el proceso actual y conserva los archivos terminados. **Reintentar fallidos** procesa únicamente los fallidos seleccionados; queda deshabilitado si no hay ninguno.

La ventana tiene tamaño mediano fijo, minimizar y cerrar. Se ajusta al espacio disponible al cambiar de monitor y no permite maximizar.

## Playlists grandes: tandas de 1.000

Cada carga prepara hasta **1.000 elementos que falten**, leyendo la playlist progresivamente. Después de descargarlos, vuelve a procesar el mismo enlace, con la misma carpeta y formato, para preparar los siguientes.

El archivo oculto `.bajada.sqlite3` guarda qué video corresponde a cada archivo, aunque su nombre ya no contenga el ID de YouTube. Antes de omitirlo se comprueba que el archivo exista. Si lo borras, vuelve a ser elegible. Otro formato se considera una descarga distinta. No borres el índice si quieres conservar esta identificación.

También se incorporan al índice las descargas terminadas de la cola anterior cuyos archivos sigan presentes. Los archivos ajenos a Bajada y los que se mueven o renombran manualmente no pueden reconocerse con seguridad por su título.

Para limitar tiempo y recursos, cada análisis revisa como máximo los primeros **200.000 elementos** y tiene un plazo de tres minutos. Si llega al límite sin preparar una tanda completa, lo indica. No intenta recorrer una playlist ilimitada ni cargarla entera en memoria.

## Estabilidad

- Cola guardada de forma atómica, con copia anterior y recuperación de descargas interrumpidas.
- Descargas y análisis fuera del hilo de la interfaz; cancelación del proceso y sus hijos.
- Límites de salida, líneas, cola y tiempo. Tres minutos sin actividad detienen la operación; la conversión tiene un margen de veinte minutos sin salida. Una descarga tiene un máximo de seis horas.
- Pausa después de cinco fallos seguidos, o ante errores de almacenamiento/componentes. Los demás elementos quedan pendientes.
- Errores de red, enlaces inválidos, metadatos defectuosos, permisos, disco lleno e índice no disponible muestran un aviso.
- Nombres sin el ID final, sin sobrescribir archivos con igual título. Usa artista y canción cuando YouTube proporciona esos campos; no identifica automáticamente una grabación por su sonido.
- Registros `errors.log` y `crash.log` junto a la cola (Windows: `%LOCALAPPDATA%\DescargaFacil`).

Ningún programa puede garantizar que nunca se cierre o se bloquee ante cualquier fallo del sistema. Estas medidas cubren los casos comprobados y permiten recuperar la cola.

## Desarrollo

Python 3.12 o 3.13. Instala `requirements-lock.txt` y ejecuta `python main.py`. Para desarrollo, FFmpeg/FFprobe y Deno deben estar disponibles en PATH o en `vendor`.

Pruebas: `python -m pip install pytest` y `python -m pytest tests -q`. Son locales y no descargan videos reales.

En Windows, `./build-windows.ps1` crea y prueba la app, descarga los componentes, compila el instalador con Inno Setup 6 y verifica una instalación silenciosa sin las herramientas del equipo en PATH. El mismo proceso se ejecuta en GitHub Actions. `--self-check` verifica componentes e inventario; `--smoke-test` abre una interfaz con cola temporal.

Los componentes tienen sus propias licencias; consulta [THIRD-PARTY.md](THIRD-PARTY.md). El código de Bajada se publica bajo MIT. Utiliza la aplicación para contenido que tengas autorización para descargar.
