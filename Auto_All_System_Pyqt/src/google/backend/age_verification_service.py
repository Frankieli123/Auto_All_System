"""
@file age_verification_service.py
@brief Google 年龄验证服务模块
@details 访问 https://myaccount.google.com/age-verification 自动完成年龄验证（优先使用付款卡）
"""

import asyncio
import time
import re
import os
import tempfile
from typing import Callable, Dict, Optional, Tuple, List

from playwright.async_api import async_playwright, Page


AGE_VERIFICATION_URL = "https://myaccount.google.com/age-verification?utm_source=p0&pli=1"
DEFAULT_COUNTRY = "United States"
DEFAULT_ZIP_CODE = "10001"
DEFAULT_CITY = "New York"
DEFAULT_STATE = "New York"
AGE_VERIFICATION_SERVICE_REV = "2026-01-24-accept-gate-1"

def _mask_card(number: str) -> str:
    if not number:
        return "****"
    last4 = number[-4:] if len(number) >= 4 else number
    return f"****{last4}"


def _normalize_exp_parts(exp_month: str, exp_year: str) -> Tuple[str, str]:
    raw_month = (exp_month or "").strip()
    raw_year = (exp_year or "").strip()

    if not raw_year and raw_month:
        m = re.search(r"(\d{1,2})\s*[/\-]\s*(\d{2,4})", raw_month)
        if m:
            raw_month, raw_year = m.group(1), m.group(2)

    mm = "".join(ch for ch in raw_month if ch.isdigit())
    yy = "".join(ch for ch in raw_year if ch.isdigit())

    if not yy:
        if len(mm) == 4:
            mm, yy = mm[:2], mm[2:]
        elif len(mm) == 3:
            mm, yy = mm[:1], mm[1:]
    if len(yy) >= 4:
        yy = yy[-2:]
    if len(mm) == 1:
        mm = f"0{mm}"
    if len(yy) == 1:
        yy = f"0{yy}"
    try:
        mm_i = int(mm) if mm else 0
        yy_i = int(yy) if yy else 0
    except ValueError:
        return mm, yy
    if mm_i > 12 and 1 <= yy_i <= 12:
        mm, yy = yy.zfill(2), str(mm_i)[-2:]
    return mm, yy


def get_card_from_db() -> Optional[dict]:
    try:
        from core.database import DBManager

        cards = DBManager.get_available_cards()
        if not cards:
            return None
        card = cards[0]
        mm, yy = _normalize_exp_parts(card.get("exp_month", ""), card.get("exp_year", ""))
        zip_code = str(card.get("zip_code") or "").strip() or DEFAULT_ZIP_CODE
        country = str(card.get("country") or "").strip() or DEFAULT_COUNTRY
        return {
            "id": card.get("id"),
            "number": card.get("card_number", ""),
            "exp_month": mm,
            "exp_year": yy,
            "cvv": card.get("cvv", ""),
            "zip": zip_code,
            "holder_name": card.get("holder_name", "") or "",
            "country": country,
            "state": card.get("state", "") or "",
            "city": card.get("city", "") or "",
            "address": card.get("address", "") or card.get("billing_address", "") or "",
        }
    except Exception as e:
        print(f"[AgeVerify] 获取卡片失败: {e}")
        return None


def update_card_usage(card_id: int):
    try:
        from core.database import DBManager

        DBManager.increment_card_usage(card_id)
    except Exception as e:
        print(f"[AgeVerify] 更新卡片使用次数失败: {e}")


def _collect_payment_frames(page: Page) -> List[object]:
    frames: List[object] = []
    for frame in page.frames:
        url = (frame.url or "").lower()
        name = (frame.name or "").lower()
        if any(k in url for k in ["payments.google.com", "pay.google.com", "tokenized.play.google.com", "buyflow", "instrumentmanager", "payment"]):
            frames.append(frame)
            continue
        if any(k in name for k in ["paymentsmodaliframe", "ucc-"]):
            frames.append(frame)
    return frames


def _is_payment_related_url(url: str) -> bool:
    u = (url or "").lower()
    return any(
        k in u
        for k in [
            "payments.google.com",
            "pay.google.com",
            "tokenized.play.google.com",
            "buyflow",
            "instrumentmanager",
            "payment",
            "modaliframe",
        ]
    )


async def _is_payments_modal_open(page: Page) -> bool:
    for selector in ("#modalIframeContainerElement", "#paymentsModalIframe", "#paymentsModalIframeContainerElement"):
        try:
            loc = page.locator(selector).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            continue
    return False


def _has_payments_popup_page(page: Page) -> bool:
    try:
        for p in page.context.pages:
            if p == page:
                continue
            try:
                if _is_payment_related_url(p.url or ""):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


async def _goto_face_verify_qr(page: Page, log: Callable[[str], None]) -> Tuple[bool, str]:
    """遇到信用卡弹窗/新窗口时，切换到人脸验证并停在扫码页（留给用户扫码）。"""

    async def _click_by_text(patterns: List[re.Pattern]) -> bool:
        for pat in patterns:
            try:
                locs = page.get_by_text(pat, exact=False)
                cnt = await locs.count()
                for i in range(min(cnt, 6)):
                    loc = locs.nth(i)
                    if not await loc.is_visible():
                        continue
                    target = await loc.evaluate_handle(
                        'el => el.closest("button,[role=button],[role=listitem],[role=option],a,[role=link]") || el'
                    )
                    if target and target.as_element():
                        await target.as_element().click(force=True)
                    else:
                        await loc.click(force=True)
                    await asyncio.sleep(1.5)
                    return True
            except Exception:
                continue
        return False

    async def _click_first_visible_button(name_re: re.Pattern) -> bool:
        try:
            btns = page.get_by_role("button", name=name_re)
            cnt = await btns.count()
            for i in range(min(cnt, 6)):
                btn = btns.nth(i)
                if await btn.is_visible():
                    await btn.click(force=True)
                    await asyncio.sleep(2)
                    return True
        except Exception:
            pass
        return False

    try:
        await page.goto(AGE_VERIFICATION_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass
    await asyncio.sleep(2)

    # 先点一次 Continue/Next（部分账号会先出现 Verify your age 的入口页）
    await _click_first_visible_button(re.compile(r"continue|next|verify|start|开始|继续|下一步|验证", re.I))

    try:
        await page.wait_for_selector('a[href*="age-verification/"]', timeout=15000)
    except Exception:
        pass

    face_patterns = [
        re.compile(r"video\\s*selfie", re.I),
        re.compile(r"selfie\\s*video", re.I),
        re.compile(r"take\\s+a\\s+selfie", re.I),
        re.compile(r"video\\s*verification", re.I),
        re.compile(r"face\\s*verification", re.I),
        re.compile(r"verify\\s+with\\s+(?:a\\s+)?selfie", re.I),
        re.compile(r"scan\\s+your\\s+face", re.I),
        re.compile(r"人脸|自拍|视频自拍|视频验证|刷脸", re.I),
    ]

    clicked_face = False
    try:
        selfie_link = page.locator('a[href*="age-verification/selfie"], a[href*="/age-verification/selfie"]').first
        if await selfie_link.count() > 0 and await selfie_link.is_visible():
            await selfie_link.click(force=True)
            await asyncio.sleep(2)
            clicked_face = True
    except Exception:
        clicked_face = False

    if not clicked_face:
        clicked_face = await _click_by_text(face_patterns)

    if not clicked_face:
        return False, "未找到“人脸/自拍视频”验证入口（需要人工选择到扫码页）"

    # 进入下一步：通常会出现扫码页（QR）
    await _click_first_visible_button(re.compile(r"continue|next|start|verify|confirm|继续|下一步|开始|验证|确认", re.I))

    qr_phrases = [
        re.compile(r"qr\\s*code", re.I),
        re.compile(r"scan\\s+(?:the|this)\\s+code", re.I),
        re.compile(r"use\\s+your\\s+phone", re.I),
        re.compile(r"open\\s+your\\s+camera", re.I),
        re.compile(r"扫码|二维码|用手机|打开相机", re.I),
    ]

    start = time.time()
    while time.time() - start < 60:
        try:
            if "privateid.com" in (page.url or "").lower():
                return True, "已切换到人脸验证扫码页（请手动扫码完成）"
        except Exception:
            pass
        try:
            for p in page.context.pages:
                try:
                    if "privateid.com" in (p.url or "").lower():
                        return True, "已切换到人脸验证扫码页（请手动扫码完成）"
                except Exception:
                    continue
        except Exception:
            pass
        try:
            if await page.locator('img[alt*="QR" i], img[src*="qr" i], svg[aria-label*="QR" i]').first.is_visible():
                return True, "已切换到人脸验证扫码页（请手动扫码完成）"
        except Exception:
            pass
        try:
            body = await page.inner_text("body")
            if any(p.search(body or "") for p in qr_phrases):
                return True, "已切换到人脸验证扫码页（请手动扫码完成）"
        except Exception:
            pass
        await asyncio.sleep(1)

    return True, "已切换到人脸验证流程，请在浏览器中扫码完成"


def _find_buyflow_frame(page: Page) -> Optional[object]:
    for frame in page.frames:
        url = (frame.url or "").lower()
        if ("payments.google.com" in url) or ("pay.google.com" in url):
            if any(k in url for k in ["buyflow", "instrumentmanager", "payment", "payments"]):
                return frame
    for frame in page.frames:
        url = (frame.url or "").lower()
        if ("payments.google.com" in url) or ("pay.google.com" in url):
            return frame
    return None


async def _wait_for_buyflow_frame(page: Page, timeout: float = 15.0) -> Optional[object]:
    start = time.time()
    while time.time() - start < timeout:
        fr = _find_buyflow_frame(page)
        if fr:
            return fr
        await asyncio.sleep(0.5)
    return None


async def _select_country_in_frame(
    page: Page, frame, candidates: List[str], log: Callable[[str], None]
) -> bool:
    async def _first_visible(locator):
        if await locator.count() > 0 and await locator.first.is_visible():
            return locator.first
        return None

    async def _combo_text(combo) -> str:
        try:
            return ((await combo.inner_text()) or "").strip()
        except Exception:
            try:
                return ((await combo.text_content()) or "").strip()
            except Exception:
                return ""

    async def _is_selected(combo) -> bool:
        text = (await _combo_text(combo)).lower()
        return any((c or "").lower() in text for c in candidates if c)

    option_pattern = re.compile("|".join(re.escape(c) for c in candidates if c), re.I)

    async def _click_option() -> bool:
        try:
            listbox = await _first_visible(frame.locator('[role="listbox"]'))
            if listbox:
                option = listbox.locator('[role="option"]').filter(has_text=option_pattern).first
                if await option.count() > 0 and await option.first.is_visible():
                    await option.first.scroll_into_view_if_needed()
                    await option.first.click(force=True)
                    return True
        except Exception:
            pass
        try:
            option = frame.locator('[role="option"]').filter(has_text=option_pattern).first
            if await option.count() > 0 and await option.first.is_visible():
                await option.first.scroll_into_view_if_needed()
                await option.first.click(force=True)
                return True
        except Exception:
            pass
        return False

    try:
        select = await _first_visible(
            frame.locator(
                'select[autocomplete="country"], select[aria-label*="Country"], select[aria-label*="Country/region"], select[name*="country"]'
            )
        )
        if select:
            for candidate in candidates:
                if not candidate:
                    continue
                try:
                    await select.select_option(label=candidate)
                    return True
                except Exception:
                    try:
                        await select.select_option(value=candidate)
                        return True
                    except Exception:
                        continue
    except Exception:
        pass

    for candidate in candidates:
        if not candidate:
            continue
        try:
            changed = await frame.evaluate(
                """(country) => {
                    const selects = Array.from(document.querySelectorAll('select'));
                    for (const sel of selects) {
                        const opts = Array.from(sel.options || []);
                        const target = opts.find(o => (o.textContent || '').trim() === country);
                        if (target) {
                            sel.value = target.value;
                            sel.dispatchEvent(new Event('change', { bubbles: true }));
                            sel.dispatchEvent(new Event('input', { bubbles: true }));
                            return true;
                        }
                    }
                    return false;
                }""",
                candidate,
            )
            if changed:
                return True
        except Exception:
            pass

    combo_candidates = [
        frame.locator('[role="combobox"][aria-label*="Country"], [role="combobox"][aria-label*="Country/region"]').first,
        frame.locator('[role="button"][aria-haspopup="listbox"][aria-label*="Country"]').first,
        frame.get_by_role("combobox", name=re.compile(r"country|region|国家|地区", re.I)).first,
    ]
    for combo in combo_candidates:
        try:
            if await combo.count() == 0 or not await combo.first.is_visible():
                continue
            combo = combo.first
            if await _is_selected(combo):
                return True
            await combo.scroll_into_view_if_needed()
            await combo.click(force=True)
            await asyncio.sleep(0.5)
            if await _click_option():
                return True
            try:
                for candidate in candidates:
                    if not candidate:
                        continue
                    await page.keyboard.type(candidate, delay=40)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(0.5)
                    if await _is_selected(combo):
                        return True
            except Exception:
                pass
        except Exception:
            continue

    try:
        label = frame.get_by_text(re.compile(r"Country/region|Country|国家|地区", re.I), exact=False).first
        if await label.count() > 0 and await label.is_visible():
            parent = label.locator("xpath=..")
            for _ in range(4):
                combo = parent.locator('[role="button"], [role="combobox"]').first
                if await combo.count() > 0 and await combo.is_visible():
                    await combo.click(force=True)
                    await asyncio.sleep(0.5)
                    if await _click_option():
                        return True
                parent = parent.locator("xpath=..")
    except Exception:
        pass

    for candidate in candidates:
        if not candidate:
            continue
        try:
            clicked = await frame.evaluate(
                """(country) => {
                    const targets = Array.from(document.querySelectorAll('[role=\"option\"], li, div'));
                    for (const el of targets) {
                        const text = (el.textContent || '').trim();
                        if (text === country) {
                            el.scrollIntoView({block: 'center'});
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""",
                candidate,
            )
            if clicked:
                return True
        except Exception:
            pass

    log(f"未能选择国家/地区: {candidates[0] if candidates else ''}")
    return False


def _normalize_country(value: str) -> str:
    if not value:
        return ""
    val = value.strip()
    upper = val.upper()
    if upper in {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
        return "United States"
    if upper in {"CN", "CHN", "CHINA", "PRC", "PEOPLE'S REPUBLIC OF CHINA"} or val in {"中国", "中國"}:
        return "China"
    return val


async def _select_country(page: Page, country_label: str, log: Callable[[str], None]) -> bool:
    """尝试在 payments/buyflow iframe 中选择 Country/region（多语言兜底）"""
    normalized = _normalize_country(country_label)
    if not normalized:
        return False

    candidates = [normalized]
    if normalized == "China":
        candidates += ["中国", "中國"]
    elif normalized == "United States":
        candidates += ["美国", "美國"]

    frames = []
    try:
        buyflow = await _wait_for_buyflow_frame(page, timeout=10.0)
        if buyflow:
            frames.append(buyflow)
    except Exception:
        buyflow = None

    for fr in _collect_payment_frames(page):
        if fr not in frames:
            frames.append(fr)
    for fr in page.frames:
        if fr not in frames:
            frames.append(fr)

    for fr in frames:
        if fr == page.main_frame:
            continue
        try:
            if await _select_country_in_frame(page, fr, candidates, log):
                return True
        except Exception:
            continue

    log(f"未能选择国家/地区: {normalized}")
    return False


async def _has_card_number_input(page: Page) -> bool:
    selectors = [
        'input[autocomplete="cc-number"]',
        'input[aria-label*="Card number"]',
        'input[placeholder*="Card number"]',
        'input[name*="cardnumber"]',
        'input[name*="cardNumber"]',
        'input[id*="cardNumber"]',
        'input[aria-label*="卡号"]',
    ]
    label_pattern = re.compile(r"card\s*number|卡号", re.I)
    role_pattern = re.compile(r"card\s*number|卡号", re.I)
    for frame in page.frames:
        for selector in selectors:
            try:
                loc = frame.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    return True
            except Exception:
                continue
        try:
            loc = frame.get_by_label(label_pattern).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            pass
        try:
            loc = frame.get_by_role("textbox", name=role_pattern).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            pass
    try:
        for selector in selectors:
            loc = page.locator(selector).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
    except Exception:
        pass
    try:
        loc = page.get_by_label(label_pattern).first
        if await loc.count() > 0 and await loc.is_visible():
            return True
    except Exception:
        pass
    try:
        loc = page.get_by_role("textbox", name=role_pattern).first
        if await loc.count() > 0 and await loc.is_visible():
            return True
    except Exception:
        pass
    return False


async def _has_card_inputs(page: Page) -> bool:
    if await _has_card_number_input(page):
        return True

    keywords = [
        "card number",
        "cardnumber",
        "cc-number",
        "card_number",
        "security code",
        "cvc",
        "cvv",
        "csc",
        "expiration",
        "expiry",
        "mm/yy",
    ]
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        name = frame.name or ""
        url = frame.url or ""
        title = ""
        aria = ""
        name_attr = ""
        try:
            frame_el = await frame.frame_element()
            if frame_el:
                title = (await frame_el.get_attribute("title")) or ""
                aria = (await frame_el.get_attribute("aria-label")) or ""
                name_attr = (await frame_el.get_attribute("name")) or ""
        except Exception:
            pass
        meta = f"{name} {name_attr} {title} {aria} {url}".lower()
        if not any(k in meta for k in keywords):
            continue
        try:
            loc = frame.locator("input").first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            continue

    return False


async def _wait_for_card_inputs(page: Page, timeout: float = 12.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if await _has_card_inputs(page):
            return True
        await asyncio.sleep(0.5)
    return False


async def _click_add_credit_card(page: Page, log: Callable[[str], None], log_not_found: bool = False) -> bool:
    keywords = [
        "+ Add credit card",
        "Add credit card",
        "Add a credit card",
        "Add card",
        "Add a card",
        "Add payment card",
        "Add payment method",
        "添加信用卡",
        "添加银行卡",
        "添加卡",
        "新增信用卡",
        "新增银行卡",
    ]
    role_name_pattern = re.compile(
        r"(?:^\s*\+\s*)?(?:add\s+(?:a\s+)?)?(?:credit\s+card|payment\s+method|payment\s+card)|"
        r"(?:^\s*\+\s*)?add\s+card|"
        r"(?:新增|添加)(?:信用卡|银行卡|卡)",
        re.I,
    )
    selectors = [
        'button:has-text("Add credit card")',
        '[role="button"]:has-text("Add credit card")',
        '[role="option"]:has-text("Add credit card")',
        '[role="listitem"]:has-text("Add credit card")',
        '[role="link"]:has-text("Add credit card")',
        '[jsaction]:has-text("Add credit card")',
        '[data-ur]:has-text("Add credit card")',
        'button:has-text("Add a credit card")',
        '[role="button"]:has-text("Add a credit card")',
        '[role="option"]:has-text("Add a credit card")',
        'button:has-text("Add card")',
        '[role="button"]:has-text("Add card")',
        '[role="option"]:has-text("Add card")',
        'button:has-text("Add payment method")',
        '[role="button"]:has-text("Add payment method")',
        '[role="option"]:has-text("Add payment method")',
        'button:has-text("添加信用卡")',
        '[role="button"]:has-text("添加信用卡")',
        '[role="option"]:has-text("添加信用卡")',
        'button:has-text("添加银行卡")',
        '[role="button"]:has-text("添加银行卡")',
        '[role="option"]:has-text("添加银行卡")',
        'button:has-text("添加卡")',
        '[role="button"]:has-text("添加卡")',
        '[role="option"]:has-text("添加卡")',
    ]

    scopes = [page] + _collect_payment_frames(page) + list(page.frames)
    seen = set()
    for scope in scopes:
        sid = id(scope)
        if sid in seen:
            continue
        seen.add(sid)
        try:
            role_loc = scope.get_by_role("option", name=role_name_pattern)
            cnt = await role_loc.count()
            for i in range(min(cnt, 5)):
                try:
                    loc = role_loc.nth(i)
                    if await loc.is_visible():
                        await loc.scroll_into_view_if_needed()
                        target = loc
                        try:
                            inner = loc.locator("img, svg, [role=img]").first
                            if await inner.count() > 0 and await inner.is_visible():
                                target = inner
                        except Exception:
                            pass
                        await target.click(force=True)
                        log("点击添加信用卡: role=option")
                        await asyncio.sleep(2)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        for selector in selectors:
            try:
                loc = scope.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.scroll_into_view_if_needed()
                    await loc.click(force=True)
                    log(f"点击添加信用卡: {selector}")
                    await asyncio.sleep(2)
                    return True
            except Exception:
                continue
        for keyword in keywords:
            try:
                loc = scope.get_by_text(keyword, exact=False).first
                if await loc.count() > 0 and await loc.is_visible():
                    target = await loc.evaluate_handle(
                        """
                        el => {
                          let node = el;
                          while (node && node !== document.body) {
                            if (
                              node.tagName === 'BUTTON' ||
                              node.getAttribute('role') === 'button' ||
                              node.getAttribute('role') === 'link' ||
                              node.getAttribute('role') === 'option' ||
                              node.getAttribute('role') === 'listitem' ||
                              node.hasAttribute('jsaction') ||
                              node.hasAttribute('data-ur') ||
                              node.hasAttribute('tabindex')
                            ) {
                              return node;
                            }
                            node = node.parentElement;
                          }
                          return el;
                        }
                        """
                    )
                    el = target.as_element()
                    if el:
                        await el.scroll_into_view_if_needed()
                        try:
                            await el.click(force=True)
                        except Exception:
                            await scope.evaluate("el => el.click()", target)
                    else:
                        await loc.scroll_into_view_if_needed()
                        await loc.click(force=True)
                    log(f"点击添加信用卡: {keyword}")
                    await asyncio.sleep(2)
                    return True
            except Exception:
                continue

    if log_not_found:
        log("未检测到“添加信用卡”按钮（可能已在卡输入表单）")
    return False


async def _click_accept_button(page: Page, log: Callable[[str], None]) -> bool:
    selectors = [
        'button:has-text("Accept")',
        'button:has-text("I agree")',
        'button:has-text("Continue")',
        'button:has-text("Next")',
        'button:has-text("Verify")',
        'button:has-text("Confirm")',
        'button:has-text("Submit")',
        'button:has-text("Save and submit")',
        'button:has-text("Save")',
        'button:has-text("OK")',
        'button:has-text("确定")',
        'button:has-text("确认")',
        'button:has-text("继续")',
        'button:has-text("同意")',
        '[role="button"]:has-text("Accept")',
        '[role="button"]:has-text("Continue")',
        '[role="button"]:has-text("Next")',
        '[role="button"]:has-text("Verify")',
        '[role="button"]:has-text("Confirm")',
        '[role="button"]:has-text("Submit")',
        '[role="button"]:has-text("Save and submit")',
        '[role="button"]:has-text("Save")',
        '[role="button"]:has-text("确定")',
        '[role="button"]:has-text("确认")',
        '[role="button"]:has-text("继续")',
    ]
    scopes = _collect_payment_frames(page) + list(page.frames) + [page]
    seen = set()
    for scope in scopes:
        sid = id(scope)
        if sid in seen:
            continue
        seen.add(sid)
        for selector in selectors:
            try:
                loc = scope.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.scroll_into_view_if_needed()
                    try:
                        await loc.click(force=True)
                    except Exception:
                        try:
                            handle = await loc.element_handle()
                            if handle:
                                await scope.evaluate("el => el.click()", handle)
                            else:
                                raise
                        except Exception:
                            raise
                    log(f"点击确认按钮: {selector}")
                    await asyncio.sleep(2)
                    return True
            except Exception:
                continue
    return False


async def _fill_card_form_legacy(page: Page, card_info: Dict[str, str], log: Callable[[str], None]) -> bool:
    number = (card_info.get("number") or "").strip()
    mm, yy = _normalize_exp_parts(card_info.get("exp_month", ""), card_info.get("exp_year", ""))
    cvv = (card_info.get("cvv") or "").strip()
    country = str(card_info.get("country") or "").strip() or DEFAULT_COUNTRY
    zip_code = str(card_info.get("zip") or card_info.get("zip_code") or "").strip()
    holder_name = (card_info.get("holder_name") or card_info.get("name") or "").strip()
    address = (card_info.get("address") or card_info.get("billing_address") or "").strip()
    city = (card_info.get("city") or "").strip()
    state = (card_info.get("state") or "").strip()
    exp = f"{mm}/{yy}" if mm and yy else ""

    number_digits = re.sub(r"\D", "", number)

    if not number_digits or not exp or not cvv:
        log("卡信息不完整，无法进行年龄验证")
        return False

    def _is_netherlands(value: str) -> bool:
        if not value:
            return False
        if value.strip() in {"荷兰", "荷蘭"}:
            return True
        low = value.strip().lower()
        if low in {"nl", "nld"}:
            return True
        return any(k in low for k in ["netherlands", "nederland", "holland"])

    def _normalize_postal_code(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return raw
        if not _is_netherlands(country):
            return raw
        compact = re.sub(r"\s+", "", raw).upper()
        if re.fullmatch(r"\d{4}[A-Z]{2}", compact):
            return compact
        digits = re.sub(r"\D", "", compact)
        letters = re.sub(r"[^A-Z]", "", compact)
        digits = (digits + "1000")[:4]
        if digits == "0000":
            digits = "1000"
        letters = (letters + "AA")[:2]
        return f"{digits}{letters}"

    country_norm = _normalize_country(country)
    fallback_city = DEFAULT_CITY
    fallback_state = DEFAULT_STATE
    fallback_zip = DEFAULT_ZIP_CODE
    if country_norm == "China":
        fallback_city = "Beijing"
        fallback_state = "Beijing"
        fallback_zip = "100000"
    elif _is_netherlands(country):
        fallback_city = "Amsterdam"
        fallback_state = "Noord-Holland"
        fallback_zip = "1234AB"

    if not zip_code:
        zip_code = fallback_zip
        log(f"zip_code 为空，使用兜底: {zip_code}")
    if not city:
        city = fallback_city
        log(f"city 为空，使用兜底: {city}")
    if not state and fallback_state:
        state = fallback_state
        log(f"state 为空，使用兜底: {state}")
    if not address:
        address = f"{city} 1st Street".strip() if city else "1st Street"
        log("address 为空，使用兜底地址")

    zip_code_norm = _normalize_postal_code(zip_code)
    if zip_code and zip_code_norm and zip_code_norm != zip_code:
        log(f"荷兰邮编格式兜底: {zip_code} -> {zip_code_norm}")
        zip_code = zip_code_norm

    number_selectors = [
        'input[autocomplete="cc-number"]',
        'input[aria-label*="Card number"]',
        'input[placeholder*="Card number"]',
        'input[name*="cardnumber"]',
        'input[name*="cardNumber"]',
        'input[id*="cardNumber"]',
        'input[aria-label*="卡号"]',
    ]
    exp_selectors = [
        'input[autocomplete="cc-exp"]',
        'input[aria-label*="Expiry"]',
        'input[aria-label*="Expiration"]',
        'input[aria-label*="MM/YY"]',
        'input[placeholder*="MM/YY"]',
        'input[placeholder*="MM"]',
        'input[placeholder*="YY"]',
        'input[name*="exp"]',
        'input[aria-label*="有效期"]',
    ]
    cvv_selectors = [
        'input[autocomplete="cc-csc"]',
        'input[aria-label*="CVC"]',
        'input[aria-label*="Security"]',
        'input[aria-label*="Security code"]',
        'input[placeholder*="Security code"]',
        'input[placeholder*="CVC"]',
        'input[placeholder*="CVV"]',
        'input[name*="cvc"]',
        'input[name*="cvv"]',
        'input[aria-label*="安全码"]',
    ]
    zip_selectors = [
        'input[autocomplete="postal-code"]',
        'input[aria-label*="Billing zip"]',
        'input[aria-label*="ZIP"]',
        'input[placeholder*="ZIP"]',
        'input[aria-label*="Postal"]',
        'input[placeholder*="Postal"]',
        'input[name*="postal"]',
        'input[aria-label*="邮编"]',
        'input[placeholder*="邮编"]',
    ]
    name_selectors = [
        'input[autocomplete="cc-name"]',
        'input[aria-label*="Cardholder"]',
        'input[placeholder*="Cardholder"]',
        'input[aria-label*="Name on card"]',
        'input[placeholder*="Name on card"]',
        'input[name*="cardname"]',
        'input[name*="cardName"]',
        'input[aria-label*="持卡人"]',
        'input[placeholder*="持卡人"]',
        'input[aria-label*="姓名"]',
    ]

    address_selectors = [
        'input[autocomplete="address-line1"]',
        'input[aria-label*="Street"]',
        'input[placeholder*="Street"]',
        'input[aria-label*="Address"]',
        'input[placeholder*="Address"]',
        'input[name*="address"]',
        'input[aria-label*="地址"]',
        'input[placeholder*="地址"]',
    ]
    city_selectors = [
        'input[autocomplete="address-level2"]',
        'input[aria-label*="City"]',
        'input[placeholder*="City"]',
        'input[name*="city"]',
        'input[aria-label*="城市"]',
        'input[placeholder*="城市"]',
    ]
    city_select_selectors = [
        'select[autocomplete="address-level2"]',
        'select[aria-label*="City"]',
        'select[name*="city"]',
    ]
    state_input_selectors = [
        'input[autocomplete="address-level1"]',
        'input[aria-label*="State"]',
        'input[placeholder*="State"]',
        'input[name*="state"]',
        'input[aria-label*="省"]',
        'input[aria-label*="州"]',
        'input[placeholder*="省"]',
        'input[placeholder*="州"]',
    ]
    state_select_selectors = [
        'select[autocomplete="address-level1"]',
        'select[aria-label*="State"]',
        'select[name*="state"]',
    ]

    warned_missing = {"zip": False, "name": False, "address": False, "city": False, "state": False}

    async def safe_fill(loc, value: str, verify_digits: bool = False, delay_ms: int = 30) -> bool:
        expected = re.sub(r"\D", "", value) if verify_digits else value

        async def get_value() -> str:
            try:
                cur = await loc.input_value()
            except Exception:
                try:
                    cur = await loc.evaluate("el => el && (el.value || '')")
                except Exception:
                    cur = ""
            cur = cur or ""
            return re.sub(r"\D", "", cur) if verify_digits else cur

        async def clear() -> None:
            try:
                await loc.fill("")
                return
            except Exception:
                pass
            try:
                await loc.press("Control+A")
                await loc.press("Backspace")
            except Exception:
                pass

        for method, d in (("fill", 0), ("type", delay_ms), ("type", max(delay_ms, 80))):
            try:
                await loc.scroll_into_view_if_needed()
            except Exception:
                pass
            try:
                await loc.click(force=True)
            except Exception:
                pass
            await asyncio.sleep(0.15)
            await clear()
            try:
                if method == "fill":
                    await loc.fill(value)
                else:
                    await loc.type(value, delay=d)
            except Exception:
                continue
            await asyncio.sleep(0.2)
            cur = await get_value()
            if cur == expected:
                return True
        return False

    async def try_fill(scope) -> bool:
        card_number_input = None
        for selector in number_selectors:
            try:
                loc = scope.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    card_number_input = loc
                    break
            except Exception:
                continue
        if not card_number_input:
            try:
                loc = scope.get_by_label(re.compile(r"card\s*number|卡号", re.I)).first
                if await loc.count() > 0 and await loc.is_visible():
                    card_number_input = loc
            except Exception:
                pass
        if not card_number_input:
            try:
                loc = scope.get_by_role("textbox", name=re.compile(r"card\s*number|卡号", re.I)).first
                if await loc.count() > 0 and await loc.is_visible():
                    card_number_input = loc
            except Exception:
                pass
        if not card_number_input:
            return False

        if not await safe_fill(card_number_input, number_digits, verify_digits=True, delay_ms=35):
            return False

        filled_exp = False
        exp_input = None
        for selector in exp_selectors:
            try:
                loc = scope.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    exp_input = loc
                    break
            except Exception:
                continue
        if not exp_input:
            try:
                loc = scope.get_by_placeholder(re.compile(r"mm/yy", re.I)).first
                if await loc.count() > 0 and await loc.is_visible():
                    exp_input = loc
            except Exception:
                pass
        if not exp_input:
            try:
                loc = scope.get_by_role("textbox", name=re.compile(r"mm/yy|expir|有效期", re.I)).first
                if await loc.count() > 0 and await loc.is_visible():
                    exp_input = loc
            except Exception:
                pass
        if exp_input:
            try:
                await exp_input.click(force=True)
                await exp_input.fill(exp)
                filled_exp = True
            except Exception:
                try:
                    await exp_input.type(exp, delay=10)
                    filled_exp = True
                except Exception:
                    filled_exp = False

        if exp and not filled_exp:
            return False

        filled_cvv = False
        cvv_input = None
        for selector in cvv_selectors:
            try:
                loc = scope.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    cvv_input = loc
                    break
            except Exception:
                continue
        if not cvv_input:
            try:
                loc = scope.get_by_placeholder(re.compile(r"security\s*code|cvc|cvv", re.I)).first
                if await loc.count() > 0 and await loc.is_visible():
                    cvv_input = loc
            except Exception:
                pass
        if not cvv_input:
            try:
                loc = scope.get_by_role("textbox", name=re.compile(r"security\s*code|cvc|cvv|安全码", re.I)).first
                if await loc.count() > 0 and await loc.is_visible():
                    cvv_input = loc
            except Exception:
                pass
        if cvv_input:
            filled_cvv = await safe_fill(cvv_input, cvv, verify_digits=True, delay_ms=35)

        if cvv and not filled_cvv:
            return False

        if zip_code:
            zip_input = None
            for selector in zip_selectors:
                try:
                    loc = scope.locator(selector).first
                    if await loc.count() > 0 and await loc.is_visible():
                        zip_input = loc
                        break
                except Exception:
                    continue
            if zip_input:
                try:
                    await zip_input.click(force=True)
                    await zip_input.fill(zip_code)
                except Exception:
                    try:
                        await zip_input.type(zip_code, delay=10)
                    except Exception:
                        pass
        else:
            if not warned_missing["zip"]:
                try:
                    for selector in zip_selectors:
                        loc = scope.locator(selector).first
                        if await loc.count() > 0 and await loc.is_visible():
                            log("检测到邮编输入框，但卡信息未提供 zip_code")
                            warned_missing["zip"] = True
                            break
                except Exception:
                    pass
        if holder_name:
            name_input = None
            for selector in name_selectors:
                try:
                    loc = scope.locator(selector).first
                    if await loc.count() > 0 and await loc.is_visible():
                        name_input = loc
                        break
                except Exception:
                    continue
            if name_input:
                try:
                    await name_input.click(force=True)
                    await name_input.fill(holder_name)
                except Exception:
                    try:
                        await name_input.type(holder_name, delay=10)
                    except Exception:
                        pass
        else:
            if not warned_missing["name"]:
                try:
                    for selector in name_selectors:
                        loc = scope.locator(selector).first
                        if await loc.count() > 0 and await loc.is_visible():
                            log("检测到持卡人输入框，但卡信息未提供 holder_name")
                            warned_missing["name"] = True
                            break
                except Exception:
                    pass

        if address:
            address_input = None
            for selector in address_selectors:
                try:
                    loc = scope.locator(selector).first
                    if await loc.count() > 0 and await loc.is_visible():
                        address_input = loc
                        break
                except Exception:
                    continue
            if address_input:
                try:
                    await address_input.click(force=True)
                    await address_input.fill(address)
                except Exception:
                    try:
                        await address_input.type(address, delay=10)
                    except Exception:
                        pass
        else:
            address_input = None
            for selector in address_selectors:
                try:
                    loc = scope.locator(selector).first
                    if await loc.count() > 0 and await loc.is_visible():
                        address_input = loc
                        break
                except Exception:
                    continue
            if address_input:
                fallback = ((city or state or "").strip() + " 1st Street").strip()
                if not fallback:
                    fallback = "1st Street"
                try:
                    await address_input.click(force=True)
                    await address_input.fill(fallback)
                    log("address 为空，已写入兜底地址")
                except Exception:
                    try:
                        await address_input.type(fallback, delay=10)
                        log("address 为空，已写入兜底地址")
                    except Exception:
                        pass
            elif not warned_missing["address"]:
                log("检测到地址输入框，但卡信息未提供 address")
                warned_missing["address"] = True

        if city:
            city_input = None
            for selector in city_selectors:
                try:
                    loc = scope.locator(selector).first
                    if await loc.count() > 0 and await loc.is_visible():
                        city_input = loc
                        break
                except Exception:
                    continue
            if city_input:
                try:
                    await city_input.click(force=True)
                    await city_input.fill(city)
                except Exception:
                    try:
                        await city_input.type(city, delay=10)
                    except Exception:
                        pass
            else:
                city_select = None
                for selector in city_select_selectors:
                    try:
                        sel = scope.locator(selector).first
                        if await sel.count() > 0 and await sel.is_visible():
                            city_select = sel
                            break
                    except Exception:
                        continue
                if city_select:
                    try:
                        await city_select.select_option(label=city)
                    except Exception:
                        try:
                            await city_select.select_option(value=city)
                        except Exception:
                            for idx in (1, 0):
                                try:
                                    await city_select.select_option(index=idx)
                                    log("city 未匹配，已从下拉选择兜底城市")
                                    break
                                except Exception:
                                    continue
        else:
            if not warned_missing["city"]:
                try:
                    for selector in city_selectors:
                        loc = scope.locator(selector).first
                        if await loc.count() > 0 and await loc.is_visible():
                            log("检测到城市输入框，但卡信息未提供 city")
                            warned_missing["city"] = True
                            break
                except Exception:
                    pass

        if state:
            filled_state = False
            state_select = None
            for selector in state_select_selectors:
                try:
                    sel = scope.locator(selector).first
                    if await sel.count() > 0 and await sel.is_visible():
                        state_select = sel
                        try:
                            await sel.select_option(label=state)
                            filled_state = True
                        except Exception:
                            try:
                                await sel.select_option(value=state)
                                filled_state = True
                            except Exception:
                                filled_state = False
                        break
                except Exception:
                    continue
            if not filled_state and state_select:
                for idx in (1, 0):
                    try:
                        await state_select.select_option(index=idx)
                        filled_state = True
                        log("state 未匹配，已从下拉选择兜底省/州")
                        break
                    except Exception:
                        continue
            if not filled_state:
                state_input = None
                for selector in state_input_selectors:
                    try:
                        loc = scope.locator(selector).first
                        if await loc.count() > 0 and await loc.is_visible():
                            state_input = loc
                            break
                    except Exception:
                        continue
                if state_input:
                    try:
                        await state_input.click(force=True)
                        await state_input.fill(state)
                        filled_state = True
                    except Exception:
                        try:
                            await state_input.type(state, delay=10)
                            filled_state = True
                        except Exception:
                            pass
        else:
            if not warned_missing["state"]:
                try:
                    for selector in state_select_selectors + state_input_selectors:
                        loc = scope.locator(selector).first
                        if await loc.count() > 0 and await loc.is_visible():
                            log("检测到省/州输入框，但卡信息未提供 state")
                            warned_missing["state"] = True
                            break
                except Exception:
                    pass

        if cvv_input:
            try:
                cur = await cvv_input.input_value()
            except Exception:
                try:
                    cur = await cvv_input.evaluate("el => el && (el.value || '')")
                except Exception:
                    cur = ""
            if not re.sub(r"\D", "", (cur or "")):
                try:
                    await safe_fill(cvv_input, cvv, verify_digits=True, delay_ms=35)
                except Exception:
                    pass

        submit_selectors = [
            'button:has-text("Save")',
            'button:has-text("Submit")',
            'button:has-text("Continue")',
            'button:has-text("Verify")',
            'button:has-text("Confirm")',
            'button:has-text("Next")',
            'button:has-text("保存")',
            'button:has-text("提交")',
            'button:has-text("继续")',
            'button:has-text("验证")',
            'button:has-text("确认")',
            'button:has-text("下一步")',
            '[role="button"]:has-text("Save")',
            '[role="button"]:has-text("Continue")',
            '[role="button"]:has-text("Verify")',
            '[role="button"]:has-text("Confirm")',
            '[role="button"]:has-text("继续")',
            '[role="button"]:has-text("验证")',
            '[role="button"]:has-text("确认")',
        ]
        for selector in submit_selectors:
            try:
                btn = scope.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await btn.click(force=True)
                    log(f"点击提交按钮: {selector}")
                    await asyncio.sleep(2)
                    return True
            except Exception:
                continue

        try:
            await card_number_input.press("Enter")
            await asyncio.sleep(2)
            return True
        except Exception:
            return True

    scopes = _collect_payment_frames(page) + list(page.frames) + [page]
    seen = set()
    for scope in scopes:
        sid = id(scope)
        if sid in seen:
            continue
        seen.add(sid)
        if await try_fill(scope):
            return True

    # 调试信息（仅失败时输出一次）
    try:
        frames = list(page.frames)
        payment_frames = _collect_payment_frames(page)
        sample_urls = []
        for fr in payment_frames[:3]:
            try:
                sample_urls.append(fr.url)
            except Exception:
                pass
        log(f"未找到卡号输入框：frames={len(frames)}, payment_frames={len(payment_frames)}, sample={sample_urls}")
    except Exception:
        pass
    return False


async def auto_age_verification(page: Page, card_info: Dict[str, str], log: Callable[[str], None]) -> Tuple[bool, str, bool]:
    verified_phrases = [
        "You're all set",
        "You’re all set",
        "You are all set",
        "all set",
        "Your age has been verified",
        "age has been verified",
        "Age verified",
        "Your age is verified",
        "You've already verified your age",
        "You’ve already verified your age",
        "Thank you for confirming you’re old enough to use certain Google services",
        "您的年龄已验证",
        "你的年齡已驗證",
        "已完成",
        "完成",
    ]
    need_verify_phrases = [
        "Verify your age",
        "Confirm your age",
        "Age verification required",
        "验证您的年龄",
        "确认您的年龄",
        "驗證你的年齡",
        "確認你的年齡",
    ]

    def _contains_any(text: str, phrases: List[str]) -> Optional[str]:
        low = (text or "").lower()
        for phrase in phrases:
            if (phrase or "").lower() in low:
                return phrase
        return None

    keep_open = True
    try:
        log(f"[age_verify] rev={AGE_VERIFICATION_SERVICE_REV} file={__file__}")
    except Exception:
        pass
    log(f"打开年龄验证页面: {AGE_VERIFICATION_URL}")
    try:
        await page.goto(AGE_VERIFICATION_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        return False, f"导航失败: {e}", True

    await asyncio.sleep(2)
    try:
        log(f"当前URL: {page.url}")
    except Exception:
        pass

    try:
        body_text = await page.inner_text("body")
    except Exception:
        body_text = ""

    hit = _contains_any(body_text, verified_phrases)
    if hit:
        try:
            card_info["__age_verify_used_card"] = False
        except Exception:
            pass
        return True, f"年龄已验证 ({hit})", True

    # 年龄验证全部改为“扫脸/Take a selfie”，到扫码页即算完成并保持浏览器打开
    try:
        card_info["__age_verify_used_card"] = False
    except Exception:
        pass
    ok2, msg2 = await _goto_face_verify_qr(page, log)
    return ok2, msg2, True


def process_age_verification(
    browser_id: str,
    card_info: Optional[dict] = None,
    log_callback: Callable[[str], None] = None,
) -> Tuple[bool, str]:
    def log(msg: str):
        print(msg)
        if log_callback:
            log_callback(msg)

    try:
        from core.bit_api import open_browser, close_browser, get_browser_info
        from core.database import DBManager
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
                from core.database import build_account_info_from_remark

                account_info = build_account_info_from_remark(browser_info.get("remark", ""))
    except Exception:
        pass

    if card_info is None or not isinstance(card_info, dict):
        card_info = {}

    card_id = card_info.get("id")
    try:
        card_info["__age_verify_used_card"] = False
    except Exception:
        pass
    log("年龄验证模式: 扫脸（不使用信用卡），到扫码页即算完成")

    result = open_browser(browser_id)
    if not result.get("success"):
        return False, f"打开浏览器失败: {result.get('msg', '未知错误')}"

    ws_endpoint = result["data"]["ws"]

    async def _run():
        keep_open = True
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.connect_over_cdp(ws_endpoint)
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else await context.new_page()

                log("检查登录状态...")
                if account_info:
                    ok, msg = await ensure_google_login(page, account_info)
                    if not ok:
                        return False, f"登录失败: {msg}", True

                log("开始年龄验证...")
                ok, msg, keep_open = await auto_age_verification(page, card_info, log)
                used_card = True
                try:
                    used_card = bool(card_info.get("__age_verify_used_card", True))
                except Exception:
                    used_card = True
                if ok and card_id and used_card:
                    update_card_usage(card_id)
                if not ok:
                    try:
                        debug_dir = os.path.join(tempfile.gettempdir(), "auto_all_system_age_verify")
                        os.makedirs(debug_dir, exist_ok=True)
                        screenshot_path = os.path.join(
                            debug_dir, f"age_verify_{browser_id[:8]}_{int(time.time())}.png"
                        )
                        await page.screenshot(path=screenshot_path)
                        log(f"失败截图: {screenshot_path}")
                        html_path = os.path.join(
                            debug_dir, f"age_verify_{browser_id[:8]}_{int(time.time())}.html"
                        )
                        try:
                            html = await page.content()
                            with open(html_path, "w", encoding="utf-8") as f:
                                f.write(html)
                            log(f"失败HTML: {html_path}")
                            msg = f"{msg} | 截图: {screenshot_path} | HTML: {html_path}"
                        except Exception:
                            msg = f"{msg} | 截图: {screenshot_path}"

                        # 额外保存关键 iframe 的 HTML（page.content 不包含 iframe 内部 DOM）
                        try:
                            dumped = 0
                            for idx, fr in enumerate(page.frames):
                                u = (fr.url or "")
                                if "payments.google.com" not in u and "pay.google.com" not in u and "tokenized.play.google.com" not in u:
                                    continue
                                frame_html_path = os.path.join(
                                    debug_dir, f"age_verify_{browser_id[:8]}_{int(time.time())}_frame{idx}.html"
                                )
                                try:
                                    html2 = await fr.content()
                                    with open(frame_html_path, "w", encoding="utf-8") as f:
                                        f.write(html2)
                                    dumped += 1
                                except Exception:
                                    continue
                            if dumped:
                                log(f"失败FrameHTML: {dumped} 个（payments/pay/tokenized）")
                        except Exception:
                            pass
                    except Exception:
                        pass
                return ok, msg, keep_open
        except Exception as e:
            return False, str(e), True
        finally:
            if not keep_open:
                try:
                    close_browser(browser_id)
                except Exception:
                    pass

    success, message, _keep_open = asyncio.run(_run())
    return success, message
