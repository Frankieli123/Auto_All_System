from __future__ import annotations

import requests
from typing import Any, Dict, List, Optional

from .backend_config import get_geekez_api_url


class GeekezAPI:
    def __init__(self, base_url: Optional[str] = None, timeout: int = 30):
        self.base_url = (base_url or get_geekez_api_url()).rstrip("/")
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json"}

    @staticmethod
    def _looks_like_totp_secret(value: str) -> bool:
        s = (value or "").replace(" ", "").strip()
        if len(s) < 16:
            return False
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=")
        return all((c.upper() in allowed) for c in s)

    @classmethod
    def _normalize_remark(cls, remark: str) -> str:
        r = str(remark or "")
        if "----" not in r:
            return r
        parts = r.split("----")
        if len(parts) != 3:
            return r
        third = parts[2]
        if ("@" in third) and (not cls._looks_like_totp_secret(third)):
            # 更像辅助邮箱而不是2FA密钥：保持原样
            return r
        # 兼容：缺少辅助邮箱时，将最后一段视为2FA密钥
        return "----".join([parts[0], parts[1], "", parts[2]])

    @classmethod
    def _normalize_profile(cls, data: Any) -> Any:
        if isinstance(data, dict) and "remark" in data:
            data["remark"] = cls._normalize_remark(data.get("remark"))
        return data

    @staticmethod
    def _normalize_result(res: Any) -> Dict[str, Any]:
        if not isinstance(res, dict):
            return {"success": False, "msg": str(res)}
        if res.get("success") is False and not res.get("msg"):
            if res.get("error"):
                res["msg"] = str(res["error"])
            elif res.get("message"):
                res["msg"] = str(res["message"])
        return res

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    def _get(self, path: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        try:
            return self._normalize_result(requests.get(self._url(path), timeout=timeout or self.timeout).json())
        except Exception as e:
            return {"success": False, "msg": str(e)}

    def _post(self, path: str, payload: Optional[Dict[str, Any]] = None, timeout: Optional[int] = None) -> Dict[str, Any]:
        try:
            return self._normalize_result(
                requests.post(
                    self._url(path),
                    json=payload or {},
                    headers=self.headers,
                    timeout=timeout or self.timeout,
                ).json()
            )
        except Exception as e:
            return {"success": False, "msg": str(e)}

    def _patch(self, path: str, payload: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
        try:
            return self._normalize_result(
                requests.patch(
                    self._url(path),
                    json=payload,
                    headers=self.headers,
                    timeout=timeout or self.timeout,
                ).json()
            )
        except Exception as e:
            return {"success": False, "msg": str(e)}

    def _delete(self, path: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        try:
            return self._normalize_result(
                requests.delete(self._url(path), timeout=timeout or self.timeout).json()
            )
        except Exception as e:
            return {"success": False, "msg": str(e)}

    def health_check(self) -> Dict[str, Any]:
        return self._get("/health", timeout=5)

    def list_browsers(self, page: int = 0, page_size: int = 1000, **kwargs) -> Dict[str, Any]:
        res = self._get("/profiles", timeout=10)
        if not res.get("success"):
            return res
        items = (res.get("data") or {}).get("list") or []
        if not isinstance(items, list):
            items = []
        for idx, it in enumerate(items):
            if isinstance(it, dict) and "seq" not in it:
                it["seq"] = idx + 1
            cls = self.__class__
            if isinstance(it, dict) and "remark" in it:
                it["remark"] = cls._normalize_remark(it.get("remark"))
        start = max(page, 0) * max(page_size, 1)
        end = start + max(page_size, 1)
        sliced = items[start:end]
        return {"success": True, "data": {"list": sliced, "total": len(items)}}

    def get_browser_detail(self, browser_id: str) -> Dict[str, Any]:
        res = self._get(f"/profiles/{browser_id}", timeout=10)
        if res.get("success") and isinstance(res.get("data"), dict):
            res["data"] = self._normalize_profile(res.get("data"))
        return res

    def create_browser(
        self,
        name: str = "Profile",
        group_id: Optional[str] = None,
        browser_fingerprint: Optional[Dict[str, Any]] = None,
        proxy_method: int = 2,
        proxy_type: str = "noproxy",
        **kwargs,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": name,
            "proxyStr": str(kwargs.get("proxyStr") or ""),
            "remark": str(kwargs.get("remark") or ""),
        }
        fingerprint = kwargs.get("fingerprint") or browser_fingerprint
        if isinstance(fingerprint, dict):
            payload["fingerprint"] = fingerprint
        tags = kwargs.get("tags")
        if isinstance(tags, list):
            payload["tags"] = tags
        if kwargs.get("debugPort"):
            try:
                payload["debugPort"] = int(kwargs["debugPort"])
            except Exception:
                pass
        if kwargs.get("preProxyOverride"):
            payload["preProxyOverride"] = kwargs["preProxyOverride"]
        return self._post("/profiles", payload=payload, timeout=15)

    def patch_browser(self, browser_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        return self._patch(f"/profiles/{browser_id}", payload=patch, timeout=15)

    def open_browser(self, browser_id: str, args=None, queue: bool = True, **kwargs) -> Dict[str, Any]:
        style = str(kwargs.get("watermarkStyle") or "enhanced")
        res = self._post(f"/profiles/{browser_id}/open", payload={"watermarkStyle": style}, timeout=90)
        if not res.get("success"):
            return res
        data = res.get("data") or {}
        if isinstance(data, dict):
            return {"success": True, "data": {"ws": data.get("ws"), "http": data.get("http"), **data}}
        return {"success": True, "data": data}

    def close_browser(self, browser_id: str) -> Dict[str, Any]:
        return self._post(f"/profiles/{browser_id}/close", payload={}, timeout=30)

    def delete_browser(self, browser_id: str) -> Dict[str, Any]:
        return self._delete(f"/profiles/{browser_id}", timeout=30)
