# SPDX-License-Identifier: EUPL-1.2
"""What stops the receiver, as stable codes that the command line turns into translated messages."""

from __future__ import annotations

NOT_PAIRED = "not_paired"
ALREADY_PAIRED = "already_paired"
STATE_UNREADABLE = "state_unreadable"
STATE_UNSAFE = "state_unsafe"
BUSY = "busy"
FOLDER_ONLY = "folder_only"
NO_SOURCE_FOLDER = "no_source_folder"
UNSAFE_FOLDER = "unsafe_folder"
BAD_PAIRING_CODE = "bad_pairing_code"


class ReceiveError(Exception):
    """The command cannot go on; `code` says why."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
