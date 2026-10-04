"""Include the installed distributions' supplied license files in the package."""
from importlib import metadata
from pathlib import Path
import shutil, sys
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
for dist in metadata.distributions():
    name=dist.metadata.get('Name','unknown').replace('/','_')
    for entry in dist.files or []:
        label=str(entry).lower()
        if any(part in label for part in ('license','licence','copying','notice')):
            source=Path(dist.locate_file(entry))
            if source.is_file() and source.stat().st_size<2_000_000:
                target=root/name/source.name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
