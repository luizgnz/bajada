"""Destination-local index; verify real files before skipping a YouTube ID."""
import sqlite3
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from core import youtube_url


def video_id(url):
    parsed = urlparse(youtube_url(url))
    return parsed.path.strip('/') if parsed.hostname in ('youtu.be','www.youtu.be') else parse_qs(parsed.query).get('v',[''])[0]


class DownloadLibrary:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.folder / '.bajada.sqlite3', timeout=5)
        try:
            self.connection.execute('CREATE TABLE IF NOT EXISTS files (video_id TEXT NOT NULL, path TEXT NOT NULL, format TEXT NOT NULL, PRIMARY KEY(video_id,path))')
            self.connection.execute('CREATE INDEX IF NOT EXISTS files_lookup ON files(video_id,format)')
            self.connection.commit()
        except Exception:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def remember(self, identity, filename):
        path = Path(filename).resolve()
        if not identity or not path.is_relative_to(self.folder) or not path.is_file():
            return
        relative = path.relative_to(self.folder).as_posix()
        self.connection.execute('INSERT OR REPLACE INTO files VALUES(?,?,?)',
                                (identity, relative, path.suffix.lstrip('.').lower()))
        self.connection.commit()

    def seed(self, items):
        for item in items:
            if item.get('status') == 'done' and isinstance(item.get('file'),str):
                try:
                    self.remember(video_id(item['url']),item['file'])
                except (ValueError, KeyError):
                    pass

    def contains(self, identity, fmt):
        for (relative,) in self.connection.execute('SELECT path FROM files WHERE video_id=? AND format=?',
                                                   (identity,fmt.lower())):
            path = (self.folder / relative).resolve()
            if path.is_relative_to(self.folder) and path.is_file():
                return True
        return False
