import uuid
from pathlib import Path
from typing import Protocol

from app.config import settings


class StorageError(Exception):
    pass


class StorageService(Protocol):
    def write(self, user_id: uuid.UUID, file_id: uuid.UUID, data: bytes) -> str: ...
    def read(self, path: str) -> bytes: ...
    def delete(self, path: str) -> None: ...


class LocalStorageBackend:
    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir)

    def write(self, user_id: uuid.UUID, file_id: uuid.UUID, data: bytes) -> str:
        user_dir = self._base / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        path = user_dir / f"{file_id}.csv"
        path.write_bytes(data)
        return str(path)

    def read(self, path: str) -> bytes:
        p = Path(path).resolve()
        if not p.is_relative_to(self._base.resolve()):
            raise StorageError("Access denied: path outside storage root.")
        if not p.exists():
            raise StorageError(f"File not found: {path}")
        return p.read_bytes()

    def delete(self, path: str) -> None:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass


def get_storage() -> LocalStorageBackend:
    return LocalStorageBackend(settings.UPLOAD_DIR)
