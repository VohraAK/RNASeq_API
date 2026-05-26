import uuid

import pytest

from app.services.storage import LocalStorageBackend, StorageError


@pytest.fixture
def storage(tmp_path):
    return LocalStorageBackend(str(tmp_path))


def test_write_read_round_trip(storage):
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    data = b"gene1,gene2\n10,20\n"
    path = storage.write(user_id, file_id, data)
    assert storage.read(path) == data


def test_write_creates_user_subdirectory(storage, tmp_path):
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    storage.write(user_id, file_id, b"x")
    user_dir = tmp_path / str(user_id)
    assert user_dir.is_dir()


def test_write_path_contains_file_id(storage):
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    path = storage.write(user_id, file_id, b"x")
    assert str(file_id) in path


def test_write_overwrite(storage):
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    storage.write(user_id, file_id, b"first")
    path = storage.write(user_id, file_id, b"second")
    assert storage.read(path) == b"second"


def test_read_missing_file_raises_storage_error(storage):
    with pytest.raises(StorageError, match="not found"):
        storage.read(str(storage._base / "ghost.csv"))


def test_delete_removes_file(storage):
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    path = storage.write(user_id, file_id, b"data")
    storage.delete(path)
    with pytest.raises(StorageError):
        storage.read(path)


def test_delete_nonexistent_file_is_silent(storage):
    storage.delete("/tmp/does_not_exist_12345.csv")


def test_path_traversal_blocked(storage):
    # Construct a path that resolves outside the storage root
    evil_path = str(storage._base / ".." / "etc_passwd")
    with pytest.raises(StorageError, match="Access denied"):
        storage.read(evil_path)


def test_different_users_get_isolated_paths(storage):
    uid1 = uuid.uuid4()
    uid2 = uuid.uuid4()
    fid = uuid.uuid4()
    path1 = storage.write(uid1, fid, b"user1_data")
    path2 = storage.write(uid2, fid, b"user2_data")
    assert path1 != path2
    assert storage.read(path1) == b"user1_data"
    assert storage.read(path2) == b"user2_data"
