# SPDX-License-Identifier: EUPL-1.2
"""Protocol errors, identified by stable codes.

The codes are part of the protocol (specification §11): they never change meaning and are never translated. Messages
are for developers; an application shows its own translated text for each code.
"""

from __future__ import annotations

# Encoding and pairing code.
BAD_ENCODING = "bad_encoding"
BAD_PAIRING_CODE = "bad_pairing_code"
# Envelope.
TOO_LARGE = "too_large"
BAD_ENVELOPE = "bad_envelope"
UNSUPPORTED_VERSION = "unsupported_version"
UID_MISMATCH = "uid_mismatch"
SEQ_MISMATCH = "seq_mismatch"
KIND_MISMATCH = "kind_mismatch"
DECRYPTION_FAILED = "decryption_failed"
# Archive.
BAD_ARCHIVE = "bad_archive"
TOO_MANY_FILES = "too_many_files"
UNEXPECTED_FILE = "unexpected_file"
MISSING_FILE = "missing_file"
FILE_TOO_LARGE = "file_too_large"
# Signature and content.
BAD_SIGNATURE = "bad_signature"
BAD_ROTATION = "bad_rotation"
BAD_MANIFEST = "bad_manifest"
HASH_MISMATCH = "hash_mismatch"
BAD_ITEMS = "bad_items"
BAD_SUBSCRIPTION = "bad_subscription"
# Requests.
BAD_AUTHORIZATION = "bad_authorization"
BAD_DATE = "bad_date"
STALE_DATE = "stale_date"

CODES = frozenset(
    {
        BAD_ENCODING,
        BAD_PAIRING_CODE,
        TOO_LARGE,
        BAD_ENVELOPE,
        UNSUPPORTED_VERSION,
        UID_MISMATCH,
        SEQ_MISMATCH,
        KIND_MISMATCH,
        DECRYPTION_FAILED,
        BAD_ARCHIVE,
        TOO_MANY_FILES,
        UNEXPECTED_FILE,
        MISSING_FILE,
        FILE_TOO_LARGE,
        BAD_SIGNATURE,
        BAD_ROTATION,
        BAD_MANIFEST,
        HASH_MISMATCH,
        BAD_ITEMS,
        BAD_SUBSCRIPTION,
        BAD_AUTHORIZATION,
        BAD_DATE,
        STALE_DATE,
    }
)


class ProtocolError(Exception):
    """Something received does not follow the protocol, or fails a check. `code` is stable."""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in CODES:
            raise ValueError(f"unknown protocol error code {code!r}")
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)
