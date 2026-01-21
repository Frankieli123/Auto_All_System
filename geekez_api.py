import requests

from backend_config import get_geekez_api_url

headers = {"Content-Type": "application/json"}


def _url(path: str) -> str:
    base = get_geekez_api_url()
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def health(timeout: int = 3) -> dict:
    try:
        return requests.get(_url("/health"), timeout=timeout).json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_profiles(timeout: int = 5) -> list:
    try:
        res = requests.get(_url("/profiles"), timeout=timeout).json()
        if res.get("success") is True:
            return (res.get("data") or {}).get("list") or []
    except Exception:
        pass
    return []


def create_profile(name: str, proxy_str: str = "", remark: str = "", fingerprint: dict | None = None,
                   tags: list | None = None, debug_port: int | None = None, pre_proxy_override: str | None = None,
                   timeout: int = 10) -> dict:
    payload: dict = {"name": name, "proxyStr": proxy_str, "remark": remark}
    if fingerprint is not None:
        payload["fingerprint"] = fingerprint
    if tags is not None:
        payload["tags"] = tags
    if debug_port:
        payload["debugPort"] = int(debug_port)
    if pre_proxy_override:
        payload["preProxyOverride"] = pre_proxy_override

    try:
        return requests.post(_url("/profiles"), json=payload, headers=headers, timeout=timeout).json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_profile(profile_id: str, timeout: int = 5) -> dict | None:
    try:
        res = requests.get(_url(f"/profiles/{profile_id}"), timeout=timeout).json()
        if res.get("success") is True:
            return res.get("data") or {}
    except Exception:
        pass
    return None


def patch_profile(profile_id: str, patch: dict, timeout: int = 10) -> dict:
    try:
        return requests.patch(_url(f"/profiles/{profile_id}"), json=patch, headers=headers, timeout=timeout).json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def openBrowser(profile_id: str, watermark_style: str = "enhanced", timeout: int = 60) -> dict:
    """
    为了复用现有 BitBrowser 自动化代码，保持返回结构与 bit_api.openBrowser 一致：
    {success: bool, data: {ws: str, http: str|None, ...}}
    """
    payload = {"watermarkStyle": watermark_style}
    try:
        res = requests.post(
            _url(f"/profiles/{profile_id}/open"),
            json=payload,
            headers=headers,
            timeout=timeout,
        ).json()
    except Exception as e:
        return {"success": False, "error": str(e)}

    if res.get("success") is True:
        data = res.get("data") or {}
        return {"success": True, "data": {"ws": data.get("ws"), "http": data.get("http"), **data}}
    return res


def closeBrowser(profile_id: str, timeout: int = 20) -> dict:
    try:
        res = requests.post(_url(f"/profiles/{profile_id}/close"), headers=headers, timeout=timeout).json()
        if res.get("success") is True:
            return {"success": True, "data": res.get("data")}
        return res
    except Exception as e:
        return {"success": False, "error": str(e)}


def deleteBrowser(profile_id: str, timeout: int = 30) -> dict:
    try:
        res = requests.delete(_url(f"/profiles/{profile_id}"), timeout=timeout).json()
        if res.get("success") is True:
            return {"success": True, "data": res.get("data")}
        return res
    except Exception as e:
        return {"success": False, "error": str(e)}

