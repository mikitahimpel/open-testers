import os
import stat

import pytest

from open_testers.credentials import CredentialStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TESTERS_PASSPHRASE", "test-pass")
    return CredentialStore(tmp_path / "creds.json")


def test_empty_store(store):
    assert store.list() == []


def test_add_list_decrypt_roundtrip(store):
    summary = store.add(
        "admin",
        "username_password",
        {"username": "alice", "password": "secret-canary"},
    )
    assert summary.label == "admin"
    assert summary.kind == "username_password"
    assert len(store.list()) == 1

    secret = store.get_secret(summary.id)
    assert secret == {"username": "alice", "password": "secret-canary"}


def test_plaintext_never_on_disk(store, tmp_path):
    store.add(
        "admin",
        "username_password",
        {"username": "alice", "password": "leaky-canary-123"},
    )
    blob = (tmp_path / "creds.json").read_text()
    assert "alice" not in blob
    assert "leaky-canary-123" not in blob


def test_file_mode_is_0o600(store, tmp_path):
    store.add("x", "username_password", {"u": "v"})
    mode = stat.S_IMODE(os.stat(tmp_path / "creds.json").st_mode)
    assert mode == 0o600


def test_wrong_passphrase_raises_value_error(store, monkeypatch):
    summary = store.add("x", "username_password", {"u": "v"})
    monkeypatch.setenv("OPEN_TESTERS_PASSPHRASE", "wrong-pass")
    with pytest.raises(ValueError):
        store.get_secret(summary.id)


def test_remove(store):
    summary = store.add("x", "username_password", {"u": "v"})
    assert store.remove(summary.id) is True
    assert store.remove("nonexistent") is False
    assert store.list() == []


def test_get_secret_missing_id_raises(store):
    with pytest.raises(KeyError):
        store.get_secret("nope")
