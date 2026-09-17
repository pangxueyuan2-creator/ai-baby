"""Private creation of new SQLite files; never truncate existing user files."""

import os
from pathlib import Path


def reserve_private_file(path: Path) -> None:
    """Exclusively create an owner-only file on POSIX; Windows inherits directory ACLs."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
