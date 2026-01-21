from backend_config import is_geekez_backend


if is_geekez_backend():
    from geekez_api import openBrowser, closeBrowser, deleteBrowser  # noqa: F401
else:
    from bit_api import openBrowser, closeBrowser, deleteBrowser  # noqa: F401

