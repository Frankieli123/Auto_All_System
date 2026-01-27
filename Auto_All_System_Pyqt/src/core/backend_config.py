import json
import os
from typing import Optional

from .config import Config

_DEFAULT_BACKEND = "bitbrowser"

_ALIASES = {
    "bit": "bitbrowser",
    "bitbrowser": "bitbrowser",
    "bit_browser": "bitbrowser",
    "geek": "geekez",
    "geekez": "geekez",
    "geekezbrowser": "geekez",
    "geekez_browser": "geekez",
}

_SETTINGS_FILE = os.path.join(Config.DATA_DIR, "app_settings.json")


def _normalize_backend(value: str) -> Optional[str]:
    v = (value or "").strip().lower()
    if not v:
        return None
    v = _ALIASES.get(v, v)
    if v in {"bitbrowser", "geekez"}:
        return v
    return None


def get_backend() -> str:
    env = _normalize_backend(os.getenv("BROWSER_BACKEND", ""))
    if env:
        return env

    try:
        if os.path.exists(_SETTINGS_FILE):
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            v = _normalize_backend(str(data.get("backend", "")))
            if v:
                return v
    except Exception:
        pass

    return _DEFAULT_BACKEND


def set_backend(value: str) -> bool:
    v = _normalize_backend(value) or _DEFAULT_BACKEND
    try:
        os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"backend": v}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def is_geekez_backend() -> bool:
    return get_backend() == "geekez"


def get_bitbrowser_api_url() -> str:
    return (os.getenv("BITBROWSER_API_URL") or Config.BITBROWSER_API_URL).rstrip("/")


def get_geekez_api_url() -> str:
    direct = (os.getenv("GEEKEZ_API_URL") or "").strip()
    if direct:
        return direct.rstrip("/")
    port = (os.getenv("GEEKEZ_API_PORT") or "").strip()
    if port.isdigit():
        return f"http://127.0.0.1:{int(port)}"
    return getattr(Config, "GEEKEZ_API_URL", "http://127.0.0.1:17555").rstrip("/")

