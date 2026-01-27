"""
@file reset_2fa_service.py
@brief Google 2FA 重置/更新服务模块
@details 自动进入 2-Step Verification 页面，添加新的 Authenticator，并提取新的 TOTP secret
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time
from typing import Callable, Optional, Tuple

import pyotp
from playwright.async_api import async_playwright, Page, Locator

TWO_STEP_VERIFICATION_URL = "https://myaccount.google.com/signinoptions/two-step-verification?hl=en&pli=1"
_AUTHENTICATOR_SETTINGS_URLS = [
    "https://myaccount.google.com/two-step-verification/authenticator?hl=en&pli=1",
    "https://myaccount.google.com/signinoptions/two-step-verification/authenticator?hl=en&pli=1",
]

_FALSE_POSITIVES = {
    "DOORGAANNAARHOOFDCONTENT",
    "SKIPTOMAINCONTEN",
    "SKIPTOMAINCONTENT",
    "GOOGLEACCOUNT",
    "AUTHENTICATOR",
    "VERIFICATIONCODE",
    "ENTERCODE",
    "SETUPKEY",
    "ACCOUNTINSTELLINGENVOORGOOGLE",
    "TERUGNAARVORIGEPAGINA",
    "BELANGRIJKEACCOUNTMELDING",
}


async def _safe_screenshot(page: Page, path: str) -> None:
    try:
        await page.screenshot(path=path, timeout=5000, animations="disabled")
    except Exception:
        pass


def _score_page_url(url: str) -> int:
    u = (url or "").strip().lower()
    if not u or u == "about:blank":
        return -10
    if u.startswith(("chrome-extension://", "edge://", "chrome://")):
        return -100
    score = 0
    if u.startswith(("http://", "https://")):
        score += 5
    if "myaccount.google.com" in u:
        score += 100
    if "accounts.google.com" in u:
        score += 60
    if "google.com" in u:
        score += 20
    return score


async def _get_work_page(context) -> Page:
    pages = []
    for p in getattr(context, "pages", []) or []:
        try:
            if p and not p.is_closed():
                pages.append(p)
        except Exception:
            continue
    if not pages:
        return await context.new_page()
    best = max(pages, key=lambda p: _score_page_url(getattr(p, "url", "")))
    if _score_page_url(getattr(best, "url", "")) < 0:
        try:
            return await context.new_page()
        except Exception:
            return best
    return best


async def _wait_twosv_ready(page: Page, timeout_ms: int = 30000) -> bool:
    deadline = time.time() + max(1, timeout_ms) / 1000.0
    while time.time() < deadline:
        try:
            if await page.locator('[data-help-context="TWO_STEP_VERIFICATION_SCREEN"]').count() > 0:
                return True
        except Exception:
            pass
        try:
            if await page.locator('a[href*="two-step-verification/"]').count() > 0:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


def _extract_secret_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"[A-Za-z2-7]{4}(?:\s+[A-Za-z2-7]{4}){3,7}",
        r"[A-Za-z2-7]{16,32}",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            clean = re.sub(r"[\s-]", "", match.strip())
            if 16 <= len(clean) <= 32 and re.match(r"^[A-Za-z2-7]+$", clean):
                upper = clean.upper()
                if upper in _FALSE_POSITIVES or any(fp in upper for fp in _FALSE_POSITIVES):
                    continue
                return clean
    return None


def _extract_secret_from_block(text: str) -> Optional[str]:
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    keyword_re = re.compile(r"(setup key|secret key|key|secret|enter key|setup)", re.I)
    candidates = []
    for idx, line in enumerate(lines):
        if keyword_re.search(line):
            candidates.append(line)
            if idx + 1 < len(lines):
                candidates.append(lines[idx + 1])
            if idx + 2 < len(lines):
                candidates.append(lines[idx + 2])
    seen = set()
    for line in candidates:
        if line in seen:
            continue
        seen.add(line)
        secret = _extract_secret_from_text(line)
        if secret:
            return secret
    cleaned = re.sub(r"\b\d+px\b", " ", text, flags=re.I)
    return _extract_secret_from_text(cleaned)


async def _find_code_input(page: Page) -> Optional[Locator]:
    selectors = [
        'input[placeholder*="Code"]',
        'input[placeholder*="code"]',
        'input[aria-label*="Code"]',
        'input[aria-label*="code"]',
        'input[type="tel"]',
        'input[inputmode="numeric"]',
        'input[autocomplete="one-time-code"]',
        'input[name*="code"]',
        'input[name*="otp"]',
        'input[type="text"][maxlength="6"]',
    ]

    dialog_loc = None
    try:
        dialog_loc = page.locator('[role="dialog"]').first
        if await dialog_loc.count() == 0 or not await dialog_loc.is_visible():
            dialog_loc = None
    except Exception:
        dialog_loc = None

    scopes = [dialog_loc, page] if dialog_loc else [page]
    for scope in scopes:
        for selector in selectors:
            try:
                loc = scope.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except Exception:
                continue

    for frame in page.frames:
        for selector in selectors:
            try:
                loc = frame.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except Exception:
                continue

    return None


async def _click_action_button(
    page: Page,
    keywords: list[str],
    log_callback: Optional[Callable] = None,
) -> bool:
    search_scopes = []
    try:
        dialog = page.locator('[role="dialog"]').first
        if await dialog.count() > 0 and await dialog.is_visible():
            search_scopes.append(dialog)
    except Exception:
        pass
    search_scopes.append(page)

    for keyword in keywords:
        for scope in search_scopes:
            try:
                loc = scope.locator(
                    f'button:has-text("{keyword}"), [role="button"]:has-text("{keyword}")'
                ).first
                if await loc.count() > 0 and await loc.is_visible():
                    try:
                        await loc.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    await loc.click(force=True)
                    await asyncio.sleep(1.5)
                    if log_callback:
                        log_callback(f"点击: {keyword}")
                    return True
            except Exception:
                continue
        for frame in page.frames:
            try:
                loc = frame.locator(
                    f'button:has-text("{keyword}"), [role="button"]:has-text("{keyword}")'
                ).first
                if await loc.count() > 0 and await loc.is_visible():
                    try:
                        await loc.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    await loc.click(force=True)
                    await asyncio.sleep(1.5)
                    if log_callback:
                        log_callback(f"点击: {keyword}")
                    return True
            except Exception:
                continue
    return False


async def _click_cant_scan(page: Page, log_callback: Optional[Callable] = None) -> bool:
    keywords = [
        "Can't scan it?",
        "Can't scan it",
        "Can't scan",
        "Can\u2019t scan it?",
        "Can\u2019t scan it",
        "Can\u2019t scan",
        "Cannot scan",
        "Enter a setup key",
        "Use a setup key",
        "手动输入",
        "无法扫描",
        "无法扫描？",
        "不能扫描",
    ]

    search_scopes: list[object] = []
    try:
        dialog = page.locator('[role="dialog"]').first
        if await dialog.count() > 0 and await dialog.is_visible():
            search_scopes.append(dialog)
    except Exception:
        pass
    search_scopes.append(page)

    for keyword in keywords:
        for scope in search_scopes:
            try:
                loc = scope.get_by_text(keyword, exact=False).first
                if await loc.count() == 0 or not await loc.is_visible():
                    continue
                try:
                    await loc.click(force=True)
                except Exception:
                    target = await loc.evaluate_handle(
                        """
                        el => {
                          let node = el;
                          while (node && node !== document.body) {
                            const role = node.getAttribute && node.getAttribute('role');
                            const jsaction = node.getAttribute && node.getAttribute('jsaction');
                            if (node.tagName === 'BUTTON' || node.tagName === 'A' || role === 'button') return node;
                            if (jsaction && jsaction.includes('click')) return node;
                            node = node.parentElement;
                          }
                          return el;
                        }
                        """
                    )
                    await target.as_element().click(force=True)
                await asyncio.sleep(2)
                if log_callback:
                    log_callback("已点击 Can't scan it?")
                return True
            except Exception:
                continue

    try:
        loc = page.locator("text=/Can[\\u2019']t scan it\\?/i").first
        if await loc.count() > 0 and await loc.is_visible():
            await loc.click(force=True)
            await asyncio.sleep(2)
            if log_callback:
                log_callback("已点击 Can't scan it?")
            return True
    except Exception:
        pass

    return False


async def _has_authenticator_added(page: Page) -> bool:
    added_selectors = [
        'text=/Added\\s+just\\s+now/i',
        'text=/Added\\s+\\d+\\s+\\w+\\s+ago/i',
        'text=/Added\\s+\\d+\\s+minutes\\s+ago/i',
        'text=/Added\\s+\\d+\\s+hours\\s+ago/i',
        'text=/Added\\s+\\d+\\s+days\\s+ago/i',
    ]
    for selector in added_selectors:
        try:
            loc = page.locator(selector)
            if await loc.count() > 0 and await loc.first.is_visible():
                return True
        except Exception:
            continue
    return False


async def _handle_password_verification(page: Page, password: str, log_callback: Optional[Callable] = None) -> bool:
    try:
        password_input = await page.query_selector('input[type="password"]')
        if not password_input or not await password_input.is_visible():
            return False

        if log_callback:
            log_callback("需要输入密码验证...")
        await password_input.fill(password)
        await asyncio.sleep(0.5)

        next_button = await page.query_selector('button[type="submit"], #passwordNext button')
        if next_button and await next_button.is_visible():
            await next_button.click()
            await asyncio.sleep(2)
            return True

        try:
            await password_input.press("Enter")
            await asyncio.sleep(2)
            return True
        except Exception:
            return True
    except Exception:
        return False


async def _maybe_select_device(page: Page) -> None:
    selectors = [
        'div:has-text("Android")',
        'div:has-text("iPhone")',
        '[role="radio"]',
    ]
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                await el.click(force=True)
                await asyncio.sleep(1)
                return
        except Exception:
            continue


async def _click_setup_authenticator(page: Page, log_callback: Optional[Callable] = None) -> bool:
    selectors = [
        'button:has-text("Set up authenticator")',
        'text="Set up authenticator"',
        'text="+ Set up authenticator"',
        'button:has-text("+ Set up")',
        'button:has-text("Configurar autenticador")',
        'a:has-text("Configurar autenticador")',
        '[role="button"]:has-text("Configurar autenticador")',
        'button:has-text("Authenticator instellen")',
        'button:has-text("+ Authenticator instellen")',
        'button:has-text("设置 Authenticator")',
        'button:has-text("设置身份验证器")',
    ]
    for selector in selectors:
        try:
            btn = await page.query_selector(selector)
            if not btn or not await btn.is_visible():
                continue
            try:
                await btn.click(timeout=5000)
            except Exception:
                try:
                    await page.evaluate(
                        """
                        el => {
                            el.dispatchEvent(new MouseEvent('click', {
                                bubbles: true,
                                cancelable: true,
                                view: window
                            }));
                        }
                        """,
                        btn,
                    )
                except Exception:
                    continue
            await asyncio.sleep(2.5)
            if log_callback:
                log_callback("已点击 Set up authenticator")
            return True
        except Exception:
            continue
    return False


async def _extract_secret_from_page(page: Page) -> Optional[str]:
    key_selectors = ['[data-secret]', '[data-otp-secret]', '[class*="secret"]', '[class*="key"]', "code", "pre"]
    for selector in key_selectors:
        try:
            elements = await page.query_selector_all(selector)
        except Exception:
            elements = []
        for el in elements:
            try:
                if not el or not await el.is_visible():
                    continue
                text = await el.inner_text()
                secret = _extract_secret_from_text(text)
                if secret:
                    return secret
            except Exception:
                continue

    try:
        dialog = await page.query_selector('[role="dialog"]')
        if dialog and await dialog.is_visible():
            secret = _extract_secret_from_block(await dialog.inner_text())
            if secret:
                return secret
    except Exception:
        pass

    try:
        secret = _extract_secret_from_block(await page.inner_text("body"))
        if secret:
            return secret
    except Exception:
        pass

    try:
        all_text_elements = await page.query_selector_all("span, div, p")
    except Exception:
        all_text_elements = []
    for element in all_text_elements:
        try:
            text = await element.inner_text()
            secret = _extract_secret_from_text(text)
            if secret:
                return secret
        except Exception:
            continue

    return None


async def _handle_existing_2fa_challenge(
    page: Page,
    secret: str,
    log_callback: Optional[Callable] = None,
) -> bool:
    try:
        code_input = await _find_code_input(page)
        if not code_input:
            return True

        clean_secret = (secret or "").replace(" ", "").strip()
        if not clean_secret:
            return False

        if log_callback:
            log_callback("正在输入现有2FA验证码...")
        code = pyotp.TOTP(clean_secret).now()
        await code_input.fill(code)
        await asyncio.sleep(0.8)

        next_button = await page.query_selector(
            'button:has-text("Next"), button:has-text("下一步"), #totpNext button, button[type="submit"]'
        )
        if next_button and await next_button.is_visible():
            await next_button.click()
            await asyncio.sleep(2)
            return True
        try:
            await code_input.press("Enter")
            await asyncio.sleep(2)
            return True
        except Exception:
            return True
    except Exception:
        return False


async def add_new_authenticator(
    page: Page,
    existing_secret: str = "",
    log_callback: Optional[Callable] = None,
) -> Optional[str]:
    if log_callback:
        log_callback("开始添加新的 Authenticator...")

    try:
        await asyncio.sleep(2)

        if "two-step-verification" not in (page.url or "") and "twosv" not in (page.url or ""):
            try:
                await page.goto(TWO_STEP_VERIFICATION_URL, timeout=60000, wait_until="domcontentloaded")
                await asyncio.sleep(2.5)
            except Exception:
                await asyncio.sleep(2.5)

        if existing_secret:
            for _ in range(2):
                if "challenge/totp" not in ((page.url or "").lower()):
                    break
                if log_callback:
                    log_callback("检测到需要输入2FA验证码（TOTP挑战页），尝试自动输入...")
                ok = await _handle_existing_2fa_challenge(page, existing_secret, log_callback)
                await asyncio.sleep(2.0)
                if not ok:
                    break

        ready = await _wait_twosv_ready(page, timeout_ms=25000)
        if not ready:
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            await asyncio.sleep(2.0)
            if existing_secret and "challenge/totp" in ((page.url or "").lower()):
                if log_callback:
                    log_callback("检测到需要输入2FA验证码（TOTP挑战页），尝试自动输入...")
                await _handle_existing_2fa_challenge(page, existing_secret, log_callback)
                await asyncio.sleep(2.0)
            ready = await _wait_twosv_ready(page, timeout_ms=25000)
        if not ready:
            if log_callback:
                log_callback("2SV页面未加载完成（Second steps 未渲染）")
            return None

        if existing_secret:
            await _handle_existing_2fa_challenge(page, existing_secret, log_callback)
            await asyncio.sleep(1.5)

        # 点击 Authenticator 行
        authenticator_row_selectors = [
            'a[href*="two-step-verification/authenticator"]',
            'div.iAwpk:has-text("Authenticator")',
            'div:has(img[src*="authenticator"]):has-text("Authenticator")',
            '[class*="iAwpk"]:has-text("Authenticator")',
            'a[href*="authenticator"]',
            'a:has-text("Authenticator")',
            'div:has-text("Authenticator"):has(svg)',
        ]

        auth_row_clicked = False
        for selector in authenticator_row_selectors:
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0:
                    try:
                        await loc.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    await loc.click(force=True)
                    auth_row_clicked = True
                    await asyncio.sleep(2.5)
                    break
            except Exception:
                continue

        if not auth_row_clicked:
            try:
                all_elements = await page.query_selector_all("div, a, span")
                for el in all_elements:
                    try:
                        text = await el.inner_text()
                    except Exception:
                        continue
                    if "Authenticator" in text and len(text) < 100:
                        try:
                            parent = await el.evaluate_handle(
                                'el => el.closest("div.iAwpk, div[class*=\\"iAwpk\\"], a")'
                            )
                            if parent:
                                await parent.as_element().click(force=True)
                            else:
                                await el.click(force=True)
                            auth_row_clicked = True
                            await asyncio.sleep(2.5)
                            break
                        except Exception:
                            continue
            except Exception:
                pass

        if not auth_row_clicked:
            for url in _AUTHENTICATOR_SETTINGS_URLS:
                try:
                    await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    await asyncio.sleep(2.0)
                    auth_row_clicked = True
                    break
                except Exception:
                    continue
        if not auth_row_clicked:
            if log_callback:
                log_callback("未找到/无法点击 Authenticator 入口")
            return None

        if existing_secret:
            await _handle_existing_2fa_challenge(page, existing_secret, log_callback)
            await asyncio.sleep(1.2)

        # 点击 Add/Set up/Change 按钮
        add_keywords = [
            "Change authenticator app",
            "Change authenticator",
            "Add authenticator app",
            "Add authenticator",
            "Set up",
            "Add",
            "Change phone",
            "Change device",
            "设置",
            "添加",
            "更换手机",
            "更换设备",
            "Get codes",
            "获取验证码",
            "toevoegen",
            "Instellen",
            "Wijzigen",
        ]

        add_button_clicked = False
        search_scopes = []
        try:
            dialog = await page.query_selector('[role="dialog"]')
            if dialog and await dialog.is_visible():
                search_scopes.append(dialog)
        except Exception:
            pass
        search_scopes.append(page)

        for keyword in add_keywords:
            if add_button_clicked:
                break
            selectors = [
                f'button:has-text("{keyword}")',
                f'[role="button"]:has-text("{keyword}")',
                f'a:has-text("{keyword}")',
            ]
            for scope in search_scopes:
                for selector in selectors:
                    try:
                        loc = scope.locator(selector).first
                        if await loc.count() > 0:
                            await loc.wait_for(state="visible", timeout=2000)
                            try:
                                await loc.scroll_into_view_if_needed()
                            except Exception:
                                pass
                            for _ in range(2):
                                try:
                                    await loc.click(force=True)
                                    add_button_clicked = True
                                    break
                                except Exception:
                                    await asyncio.sleep(0.3)
                            if add_button_clicked:
                                break
                    except Exception:
                        continue
                if add_button_clicked:
                    break

        if not add_button_clicked:
            if "authenticator" not in (page.url or ""):
                for url in _AUTHENTICATOR_SETTINGS_URLS:
                    try:
                        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                        await asyncio.sleep(2.0)
                        break
                    except Exception:
                        continue
                add_button_clicked = False
                for keyword in add_keywords:
                    if add_button_clicked:
                        break
                    if keyword in {"Add", "Set up"}:
                        continue
                    try:
                        loc = page.get_by_text(keyword, exact=False).first
                        if await loc.count() == 0 or not await loc.is_visible():
                            continue
                        try:
                            await loc.click(force=True)
                        except Exception:
                            target = await loc.evaluate_handle(
                                """
                                el => {
                                  let node = el;
                                  while (node && node !== document.body) {
                                    const role = node.getAttribute && node.getAttribute('role');
                                    const jsaction = node.getAttribute && node.getAttribute('jsaction');
                                    if (node.tagName === 'BUTTON' || node.tagName === 'A' || role === 'button') return node;
                                    if (jsaction && jsaction.includes('click')) return node;
                                    node = node.parentElement;
                                  }
                                  return el;
                                }
                                """
                            )
                            await target.as_element().click(force=True)
                        add_button_clicked = True
                        await asyncio.sleep(2.0)
                        break
                    except Exception:
                        continue
            if not add_button_clicked:
                if log_callback:
                    log_callback("未找到 Change/Add Authenticator 按钮")
                return None

        await asyncio.sleep(2.5)

        if existing_secret:
            await _handle_existing_2fa_challenge(page, existing_secret, log_callback)
            await asyncio.sleep(1.2)

        await _maybe_select_device(page)
        # 可能需要继续下一步
        await _click_action_button(
            page,
            ["Next", "Continue", "Volgende", "Weiter", "Suivant", "Siguiente", "下一步", "继续", "Set up", "设置"],
            log_callback,
        )
        await asyncio.sleep(1.5)

        await _click_cant_scan(page, log_callback)
        secret = await _extract_secret_from_page(page)
        if not secret:
            return None

        await _click_action_button(
            page,
            ["Next", "Continue", "Done", "Volgende", "Weiter", "Suivant", "Siguiente", "确认", "下一步", "继续", "完成"],
            log_callback,
        )
        return secret
    except Exception:
        return None


async def verify_new_secret(page: Page, secret: str, log_callback: Optional[Callable] = None) -> bool:
    if log_callback:
        log_callback("验证新2FA密钥...")

    try:
        code = pyotp.TOTP((secret or "").replace(" ", "").strip()).now()
    except Exception:
        return False

    try:
        code_input = await _find_code_input(page)
        if not code_input:
            await _click_action_button(
                page,
                ["Next", "Continue", "Verify", "确认", "验证", "下一步", "继续", "Done", "完成"],
                log_callback,
            )
            await asyncio.sleep(1.5)
            code_input = await _find_code_input(page)

        if not code_input:
            try:
                page_text = await page.content()
            except Exception:
                page_text = ""

            success_keywords = ["success", "done", "added", "成功", "完成", "已添加"]
            if any(k.lower() in page_text.lower() for k in success_keywords):
                return True

            error_keywords = ["error", "invalid", "wrong", "错误", "无效"]
            if any(k.lower() in page_text.lower() for k in error_keywords):
                return False

            if log_callback:
                log_callback("未找到2FA验证码输入框，无法确认是否完成验证（可能无需验证/页面变化）")
            return False

        await code_input.fill(code)
        await asyncio.sleep(0.8)

        clicked = await _click_action_button(page, ["Verify", "Next", "确认", "验证", "下一步", "Done", "完成"], log_callback)
        if not clicked:
            try:
                await code_input.press("Enter")
            except Exception:
                pass
        await asyncio.sleep(2.5)

        try:
            page_text = await page.content()
        except Exception:
            page_text = ""

        success_keywords = ["success", "done", "added", "成功", "完成", "已添加"]
        if any(k.lower() in page_text.lower() for k in success_keywords):
            return True

        error_keywords = ["error", "invalid", "wrong", "错误", "无效"]
        if any(k.lower() in page_text.lower() for k in error_keywords):
            return False

        return True
    except Exception:
        return False


def _build_remark(email: str, password: str, backup_email: str, secret: str) -> str:
    return "----".join([str(email or ""), str(password or ""), str(backup_email or ""), str(secret or "")])


def _update_browser_2fa(browser_id: str, account_info: dict, new_secret: str, log: Callable[[str], None]) -> None:
    try:
        from core.backend_config import is_geekez_backend
        from core.geekez_api import GeekezAPI
        from core.bit_api import get_api

        email = (account_info.get("email") or "").strip()
        password = account_info.get("password") or ""
        backup_email = (
            account_info.get("backup_email")
            or account_info.get("backup")
            or account_info.get("recovery_email")
            or ""
        )
        remark = _build_remark(email, password, backup_email, new_secret)

        if is_geekez_backend():
            res = GeekezAPI().patch_browser(str(browser_id), {"remark": remark})
            if not res.get("success"):
                log(f"更新Geekez备注失败: {res.get('msg') or res}")
            return

        api = get_api()
        res = api.update_browser_partial([browser_id], {"remark": remark, "faSecretKey": new_secret})
        if not res.get("success"):
            log(f"更新浏览器2FA失败: {res.get('msg') or res}")
    except Exception as e:
        log(f"更新浏览器2FA异常: {e}")


def process_reset_2fa(
    browser_id: str,
    log_callback: Optional[Callable[[str], None]] = None,
    close_after: bool = True,
) -> Tuple[bool, str]:
    def log(msg: str) -> None:
        print(msg)
        if log_callback:
            log_callback(msg)

    try:
        from core.bit_api import open_browser, close_browser, get_browser_info
        from core.database import DBManager, build_account_info_from_remark
        from google.backend.google_auth import ensure_google_login
    except ImportError as e:
        return False, f"导入失败: {e}"

    account_info = None
    try:
        row = DBManager.get_account_by_browser_id(browser_id)
        if row:
            recovery = row.get("recovery_email") or ""
            secret = row.get("secret_key") or ""
            account_info = {
                "email": row.get("email") or "",
                "password": row.get("password") or "",
                "backup": recovery,
                "backup_email": recovery,
                "secret": secret,
                "2fa_secret": secret,
            }
        else:
            browser_info = get_browser_info(browser_id)
            if browser_info:
                account_info = build_account_info_from_remark(browser_info.get("remark", ""))
    except Exception:
        pass

    if not account_info:
        return False, "未找到账号信息（DB/remark）"

    email = (account_info.get("email") or "").strip()
    password = account_info.get("password") or ""
    if not email or not password:
        return False, "账号信息不完整（需要email/password）"

    result = open_browser(browser_id)
    if not result.get("success"):
        return False, f"打开浏览器失败: {result.get('msg', '未知错误')}"
    ws_endpoint = (result.get("data") or {}).get("ws") or ""
    if not ws_endpoint:
        try:
            close_browser(browser_id)
        except Exception:
            pass
        return False, "无法获取WS端点"

    async def _run() -> Tuple[bool, str, Optional[str]]:
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.connect_over_cdp(ws_endpoint)
                context = browser.contexts[0]
                page = await _get_work_page(context)

                log("检查登录状态...")
                ok, msg = await ensure_google_login(page, account_info)
                if not ok:
                    return False, f"登录失败: {msg}", None

                log("打开2步验证设置页...")
                try:
                    await page.goto(TWO_STEP_VERIFICATION_URL, wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    pass
                await asyncio.sleep(2.5)
                await _wait_twosv_ready(page, timeout_ms=25000)

                existing_secret = (account_info.get("secret") or account_info.get("2fa_secret") or "").strip()
                if existing_secret:
                    log("检测到已有2FA密钥，开始修改2FA...")
                    await _handle_password_verification(page, password, log_callback=log_callback)
                    new_secret = await add_new_authenticator(page, existing_secret, log_callback=log_callback)
                    if not new_secret:
                        return False, f"未能获取新的2FA密钥（Authenticator） | 当前URL: {page.url}", None
                else:
                    log("当前无2FA密钥，自动走首次设置2FA...")
                    await _handle_password_verification(page, password, log_callback=log_callback)
                    ok_setup = await _click_setup_authenticator(page, log_callback=log_callback)
                    if not ok_setup:
                        await _click_action_button(
                            page,
                            ["Turn on 2-Step Verification", "Turn on", "Activar", "Aanzetten", "Inschakelen"],
                            log_callback,
                        )
                        await asyncio.sleep(2.5)
                        await _handle_password_verification(page, password, log_callback=log_callback)
                        ok_setup = await _click_setup_authenticator(page, log_callback=log_callback)
                    if not ok_setup:
                        if await _has_authenticator_added(page):
                            return True, "Authenticator已存在（未获取密钥）", None
                        return False, "未找到首次设置2FA入口（Set up authenticator）", None

                    # 进入二维码页后切换到文本密钥视图
                    await _maybe_select_device(page)
                    await _click_action_button(
                        page,
                        ["Next", "Continue", "Volgende", "Weiter", "Suivant", "Siguiente", "下一步", "继续"],
                        log_callback,
                    )
                    await asyncio.sleep(1.5)
                    await _click_cant_scan(page, log_callback)

                    new_secret = await _extract_secret_from_page(page)
                    if not new_secret:
                        if await _has_authenticator_added(page):
                            return True, "Authenticator已存在（未获取密钥）", None
                        return False, "未能提取2FA密钥", None

                    await _click_action_button(
                        page,
                        ["Next", "Continue", "Done", "Volgende", "Weiter", "Suivant", "Siguiente", "确认", "下一步", "继续", "完成"],
                        log_callback,
                    )

                verified = await verify_new_secret(page, new_secret, log_callback=log_callback)
                if verified:
                    if existing_secret:
                        return True, "2FA已更新并完成验证", new_secret
                    return True, "2FA已设置并完成验证", new_secret
                return True, "已获取新2FA密钥（验证状态未知）", new_secret
        except Exception as e:
            return False, f"异常: {e}", None

    success, message, new_secret = asyncio.run(_run())

    if new_secret:
        try:
            DBManager.update_account_secret_key(email, new_secret)
        except Exception:
            pass
        _update_browser_2fa(browser_id, account_info, new_secret, log)

    if not success:
        try:
            debug_dir = os.path.join(tempfile.gettempdir(), "auto_all_system_reset_2fa")
            os.makedirs(debug_dir, exist_ok=True)
            png = os.path.join(debug_dir, f"reset_2fa_{browser_id[:8]}_{int(time.time())}.png")
            html = os.path.join(debug_dir, f"reset_2fa_{browser_id[:8]}_{int(time.time())}.html")

            async def _dump():
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.connect_over_cdp(ws_endpoint)
                    context = browser.contexts[0]
                    page = await _get_work_page(context)
                    await _wait_twosv_ready(page, timeout_ms=5000)
                    await _safe_screenshot(page, png)
                    try:
                        content = await page.content()
                        with open(html, "w", encoding="utf-8") as f:
                            f.write(content)
                    except Exception:
                        pass

            asyncio.run(_dump())
            message = f"{message} | 截图: {png} | HTML: {html}"
        except Exception:
            pass

    if close_after:
        try:
            close_browser(browser_id)
        except Exception:
            pass
    else:
        log(f"保持浏览器打开: {browser_id}")

    return success, message
