import os


def get_backend() -> str:
    return os.getenv("BROWSER_BACKEND", "bitbrowser").strip().lower()


def get_bitbrowser_api_url() -> str:
    return os.getenv("BITBROWSER_API_URL", "http://127.0.0.1:54345").rstrip("/")


def get_geekez_api_url() -> str:
    url = os.getenv("GEEKEZ_API_URL", "").strip()
    if url:
        return url.rstrip("/")
    port = os.getenv("GEEKEZ_API_PORT", "17555").strip() or "17555"
    return f"http://127.0.0.1:{port}"


def is_geekez_backend() -> bool:
    backend = get_backend()
    return backend in {"geekez", "geekezbrowser", "geekez_browser", "geek"}

