import atexit
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch


_test_directories = tempfile.TemporaryDirectory(prefix="expense-tests-")
_test_root = Path(_test_directories.name)

os.environ["XDG_DATA_HOME"] = str(_test_root / "data")
os.environ["XDG_CACHE_HOME"] = str(_test_root / "cache")
os.environ["XDG_CONFIG_HOME"] = str(_test_root / "config")

_external_patches = [
    patch(
        "google.oauth2.service_account.Credentials.from_service_account_file",
        return_value=Mock(),
    ),
    patch("gspread.authorize", return_value=Mock()),
]
for _external_patch in _external_patches:
    _external_patch.start()


def _stop_external_patches() -> None:
    for external_patch in _external_patches:
        external_patch.stop()


atexit.register(_stop_external_patches)
