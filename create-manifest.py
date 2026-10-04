"""Record all bundled runtime files, checked once by the installer."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
if not root.is_dir():
    raise SystemExit('No existe la carpeta de componentes empaquetados.')
manifest = {}
for path in sorted(root.rglob('*')):
    if path.is_file() and path.name != 'components.json':
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        manifest[path.relative_to(root).as_posix()] = digest.hexdigest()
(root / 'components.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
