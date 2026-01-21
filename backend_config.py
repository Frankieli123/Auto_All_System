import json
import os
import sys

APP_SETTINGS_FILE = "app_settings.json"
_DEFAULT_BACKEND = "bitbrowser"
_BACKEND_ALIASES = {
    "bit": "bitbrowser",
    "bitbrowser": "bitbrowser",
    "bit_browser": "bitbrowser",
    "geek": "geekez",
    "geekez": "geekez",
    "geekezbrowser": "geekez",
    "geekez_browser": "geekez",
}
_backend_cache: str | None = None


def _base_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _settings_path() -> str:
    return os.path.join(_base_path(), APP_SETTINGS_FILE)


def _normalize_backend(value: str) -> str | None:
    v = (value or "").strip().lower()
    if not v:
        return None
    v = _BACKEND_ALIASES.get(v, v)
    if v in {"bitbrowser", "geekez"}:
        return v
    return None


def get_backend() -> str:
    global _backend_cache
    env_raw = os.getenv("BROWSER_BACKEND", "").strip()
    env = _normalize_backend(env_raw)
    if env:
        _backend_cache = env
        return env

    if _backend_cache:
        return _backend_cache

    backend = None
    try:
        path = _settings_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                backend = _normalize_backend(str(data.get("backend", "")).strip())
    except Exception:
        backend = None

    _backend_cache = backend or _DEFAULT_BACKEND
    return _backend_cache


def set_backend(backend: str) -> str:
    global _backend_cache
    value = _normalize_backend(str(backend))
    value = value or _DEFAULT_BACKEND
    _backend_cache = value

    try:
        path = _settings_path()
        data: dict = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if isinstance(existing, dict):
                    data = existing
            except Exception:
                data = {}
        data["backend"] = value
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return value


def get_bitbrowser_api_url() -> str:
    return os.getenv("BITBROWSER_API_URL", "http://127.0.0.1:54345").rstrip("/")


def get_geekez_api_url() -> str:
    url = os.getenv("GEEKEZ_API_URL", "").strip()
    if url:
        return url.rstrip("/")
    port = os.getenv("GEEKEZ_API_PORT", "17555").strip() or "17555"
    return f"http://127.0.0.1:{port}"


def is_geekez_backend() -> bool:
    return get_backend() in {"geekez", "geekezbrowser", "geekez_browser", "geek"}
