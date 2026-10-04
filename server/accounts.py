"""Player accounts: registration, login and per-account progress.

Stored as one JSON file (`server_data/accounts.json` by default):

    {
      "accounts": {
        "alice": {
          "salt": "<hex>",
          "password": "<pbkdf2-hmac-sha256 hex>",
          "created": "2026-10-02 12:00:00",
          "progress": {"inventory": {...}, "x": 500, "y": 500, "hp": 100}
        }
      }
    }

Passwords are never stored in clear text (PBKDF2-HMAC-SHA256, 120k iterations,
random salt per account). Accounts survive server restarts - unlike the world,
which is only kept in memory unless the server is started with --save.
"""

import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path

DEFAULT_ACCOUNTS_PATH = "server_data/accounts.json"

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
PASSWORD_MIN = 4
PASSWORD_MAX = 64
PBKDF2_ITERATIONS = 120_000


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()


def valid_username(name: str) -> bool:
    return bool(USERNAME_RE.match(name or ""))


def valid_password(password: str) -> bool:
    return bool(password) and PASSWORD_MIN <= len(password) <= PASSWORD_MAX


class AccountStore:
    """Thread safe account database."""

    def __init__(self, path=DEFAULT_ACCOUNTS_PATH):
        self.path = Path(path) if path else None
        self.lock = threading.RLock()
        self.accounts = {}
        self.load()

    # ------------------------------------------------------------------ file io
    def load(self) -> bool:
        if self.path is None or not self.path.exists():
            return False
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[accounts] could not read {self.path}: {exc}")
            return False
        accounts = payload.get("accounts", payload)
        if isinstance(accounts, dict):
            self.accounts = accounts
        print(f"[accounts] loaded {len(self.accounts)} account(s) from {self.path}")
        return True

    def save(self) -> bool:
        if self.path is None:
            return False
        with self.lock:
            payload = {"accounts": self.accounts}
            text = json.dumps(payload, indent=1)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, tmp_name = tempfile.mkstemp(dir=str(self.path.parent),
                                                prefix=self.path.name, suffix=".tmp")
            with os.fdopen(handle, "w", encoding="utf-8") as tmp:
                tmp.write(text)
            os.replace(tmp_name, self.path)
            return True
        except OSError as exc:
            print(f"[accounts] could not save: {exc}")
            return False

    # ------------------------------------------------------------------- checks
    def exists(self, username: str) -> bool:
        with self.lock:
            return username.lower() in {name.lower() for name in self.accounts}

    def _find_key(self, username: str):
        with self.lock:
            for name in self.accounts:
                if name.lower() == (username or "").lower():
                    return name
        return None

    # ------------------------------------------------------------------ actions
    def register(self, username: str, password: str):
        """Returns (ok, error_key, username)."""
        username = (username or "").strip()
        if not valid_username(username):
            return False, "auth.invalid_name", username
        if not valid_password(password):
            return False, "auth.short_password", username
        with self.lock:
            if self._find_key(username):
                return False, "auth.name_taken", username
            salt = secrets.token_hex(16)
            self.accounts[username] = {
                "salt": salt,
                "password": hash_password(password, salt),
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "progress": None,
            }
        self.save()
        return True, None, username

    def login(self, username: str, password: str):
        """Returns (ok, error_key, canonical_username)."""
        username = (username or "").strip()
        if not username or not password:
            return False, "auth.no_account", username
        key = self._find_key(username)
        if key is None:
            return False, "auth.no_account", username
        with self.lock:
            record = self.accounts[key]
        expected = record.get("password", "")
        actual = hash_password(password, record.get("salt", ""))
        if not secrets.compare_digest(expected, actual):
            return False, "auth.bad_password", key
        return True, None, key

    # ----------------------------------------------------------------- progress
    def get_progress(self, username: str):
        with self.lock:
            key = self._find_key(username)
            if key is None:
                return None
            return self.accounts[key].get("progress")

    def set_progress(self, username: str, progress: dict) -> bool:
        with self.lock:
            key = self._find_key(username)
            if key is None:
                return False
            self.accounts[key]["progress"] = dict(progress)
        self.save()
        return True

    def account_count(self) -> int:
        with self.lock:
            return len(self.accounts)

    def known_names(self) -> list:
        with self.lock:
            return sorted(self.accounts)
