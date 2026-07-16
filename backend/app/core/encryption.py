"""App-level encryption at rest (CLAUDE.md rule 7): clinical notes, patient
notes, medical history, and agent chat messages are all Fernet-encrypted
before they touch the database. `EncryptedString` makes this transparent to
model code — fields declare it like any other column type and never see
ciphertext; only the DB does."""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings


class DecryptionError(Exception):
    pass


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set — required to read/write health data "
            "(clinical notes, patient notes, medical history, chat messages)"
        )
    return Fernet(key.encode("ascii"))


def encrypt_text(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError("could not decrypt value — wrong key or corrupted data") from exc


class EncryptedString(TypeDecorator):
    """Stores `str` columns as Fernet ciphertext. Transparent at the ORM
    boundary — application code reads/writes plaintext `str`; only the raw
    DB row holds ciphertext."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return encrypt_text(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return decrypt_text(value)
