import os
import json
import uuid
import base64
import getpass
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidTag

STORE_PATH = Path.home() / ".open-testers" / "credentials.json"
KDF_ITERATIONS = 600_000

VALID_KINDS = {
    "username_password",
    "google_oauth",
    "github_oauth",
    "http_basic",
    "custom",
}


@dataclass
class CredentialSummary:
    id: str
    label: str
    kind: str


class CredentialStore:
    def __init__(self, path: Path = STORE_PATH):
        self.path = Path(path)

    def _passphrase(self) -> str:
        env = os.environ.get("OPEN_TESTERS_PASSPHRASE")
        if env is not None:
            return env
        return getpass.getpass("Open-testers passphrase: ")

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "credentials": []}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise RuntimeError(
                f"credentials store is corrupted at {self.path}"
            ) from e
        if not isinstance(data, dict) or "credentials" not in data:
            raise RuntimeError(
                f"credentials store is corrupted at {self.path}"
            )
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, self.path)
        os.chmod(self.path, 0o600)

    def _derive_key(self, salt: bytes, passphrase: str) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=KDF_ITERATIONS,
        )
        return kdf.derive(passphrase.encode("utf-8"))

    def list(self) -> list[CredentialSummary]:
        data = self._load()
        return [
            CredentialSummary(id=c["id"], label=c["label"], kind=c["kind"])
            for c in data["credentials"]
        ]

    def add(
        self,
        label: str,
        kind: str,
        secret: dict,
        passphrase: Optional[str] = None,
    ) -> CredentialSummary:
        if not label:
            raise ValueError("label must be non-empty")
        if kind not in VALID_KINDS:
            raise ValueError(
                f"unknown kind {kind!r}; expected one of {sorted(VALID_KINDS)}"
            )

        if passphrase is None:
            passphrase = self._passphrase()

        cred_id = str(uuid.uuid4())
        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = self._derive_key(salt, passphrase)
        plaintext = json.dumps(secret).encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, cred_id.encode())

        entry = {
            "id": cred_id,
            "label": label,
            "kind": kind,
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "tag_included": True,
        }

        data = self._load()
        data["credentials"].append(entry)
        self._save(data)

        return CredentialSummary(id=cred_id, label=label, kind=kind)

    def get_secret(
        self, cred_id: str, passphrase: Optional[str] = None
    ) -> dict:
        data = self._load()
        entry = next(
            (c for c in data["credentials"] if c["id"] == cred_id), None
        )
        if entry is None:
            raise KeyError(cred_id)

        if passphrase is None:
            passphrase = self._passphrase()

        salt = base64.b64decode(entry["salt"])
        nonce = base64.b64decode(entry["nonce"])
        ciphertext = base64.b64decode(entry["ciphertext"])
        key = self._derive_key(salt, passphrase)
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, cred_id.encode())
        except InvalidTag as e:
            raise ValueError(
                "decryption failed — wrong passphrase or tampered store"
            ) from e
        return json.loads(plaintext.decode("utf-8"))

    def remove(self, cred_id: str) -> bool:
        data = self._load()
        before = len(data["credentials"])
        data["credentials"] = [
            c for c in data["credentials"] if c["id"] != cred_id
        ]
        if len(data["credentials"]) == before:
            return False
        self._save(data)
        return True
