"""Secure persistence of the Playwright storage state (cookies + localStorage).

No credentials are ever stored or typed by the tool: a human logs in once
(including MFA) in a visible Firefox window, and only the resulting session
state is persisted — encrypted at rest with Fernet (AES-128-CBC + HMAC).
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from .logging_setup import get_logger

log = get_logger("session")


class SessionError(RuntimeError):
    pass


class SessionStore:
    def __init__(self, path: Path, encrypt: bool = True, key_env: str = "LI_SESSION_KEY",
                 key_file: Optional[Path] = None) -> None:
        self.plain_path = Path(path)
        self.enc_path = Path(str(path) + ".enc")
        self.encrypt = bool(encrypt)
        self.key_env = key_env
        self.key_file = Path(key_file) if key_file else None

    # -- key management ---------------------------------------------------
    def _key(self, create: bool = False) -> bytes:
        env_val = os.environ.get(self.key_env, "").strip()
        if env_val:
            return env_val.encode()
        if self.key_file:
            if self.key_file.exists():
                return self.key_file.read_bytes().strip()
            if create:
                self.key_file.parent.mkdir(parents=True, exist_ok=True)
                key = Fernet.generate_key()
                self.key_file.write_bytes(key)
                os.chmod(self.key_file, stat.S_IRUSR | stat.S_IWUSR)  # 0600
                log.warning("generated new session key at %s (chmod 600) — back it up "
                            "or set %s instead", self.key_file, self.key_env)
                return key
        raise SessionError(
            f"No encryption key: set ${self.key_env} or allow {self.key_file} to be created."
        )

    # -- read / write -----------------------------------------------------
    @property
    def exists(self) -> bool:
        return self.enc_path.exists() or self.plain_path.exists()

    @property
    def location(self) -> Path:
        return self.enc_path if self.enc_path.exists() else self.plain_path

    def save(self, state: Dict[str, Any]) -> Path:
        payload = json.dumps(state, separators=(",", ":")).encode()
        self.plain_path.parent.mkdir(parents=True, exist_ok=True)
        if self.encrypt:
            token = Fernet(self._key(create=True)).encrypt(payload)
            self.enc_path.write_bytes(token)
            os.chmod(self.enc_path, stat.S_IRUSR | stat.S_IWUSR)
            if self.plain_path.exists():
                self.plain_path.unlink()
            log.info("session state saved (encrypted) -> %s", self.enc_path)
            return self.enc_path
        self.plain_path.write_bytes(payload)
        os.chmod(self.plain_path, stat.S_IRUSR | stat.S_IWUSR)
        log.warning("session state saved UNENCRYPTED -> %s", self.plain_path)
        return self.plain_path

    def load(self) -> Optional[Dict[str, Any]]:
        if self.enc_path.exists():
            try:
                data = Fernet(self._key()).decrypt(self.enc_path.read_bytes())
            except InvalidToken as exc:
                raise SessionError(
                    f"Cannot decrypt {self.enc_path} — wrong ${self.key_env}/key file."
                ) from exc
            return json.loads(data)
        if self.plain_path.exists():
            return json.loads(self.plain_path.read_text())
        return None

    def cookie_names(self) -> list[str]:
        state = self.load() or {}
        return sorted({c.get("name", "") for c in state.get("cookies", [])})

    @staticmethod
    def state_from_cookies(li_at: str, jsessionid: str = "") -> Dict[str, Any]:
        """Build a storage state from cookies the operator exported themselves.

        Used only for headless servers where no display is available for the
        manual login flow (see EC2_SETUP.md).
        """
        cookies = [{
            "name": "li_at", "value": li_at, "domain": ".www.linkedin.com",
            "path": "/", "httpOnly": True, "secure": True, "sameSite": "None",
        }]
        if jsessionid:
            val = jsessionid if jsessionid.startswith('"') else f'"{jsessionid}"'
            cookies.append({
                "name": "JSESSIONID", "value": val, "domain": ".www.linkedin.com",
                "path": "/", "httpOnly": False, "secure": True, "sameSite": "None",
            })
        return {"cookies": cookies, "origins": []}
