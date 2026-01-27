"""
Google One AI Student 页面状态检测（复用 bitbrowser-automation 思路）
"""

import time
from typing import Optional, Tuple

from playwright.async_api import Page


NOT_AVAILABLE_PHRASES = [
    "This offer is not available",
    "This account isn't eligible for the Google AI Pro plan",
    "This account isn’t eligible for the Google AI Pro plan",
    "漂u 膽茫i n脿y hi峄噉 kh么ng d霉ng 膽瓢峄",
    "Esta oferta no est谩 disponible",
    "Cette offre n'est pas disponible",
    "Esta oferta n茫o est谩 dispon铆vel",
    "Tawaran ini tidak tersedia",
    "姝や紭鎯犵洰鍓嶄笉鍙敤",
    "閫欓爡鍎儬鐩墠鐒℃硶浣跨敤",
    "Oferta niedost臋pna",
    "Oferta nu este disponibil膬",
    "Die Aktion ist nicht verf眉gbar",
    "Il'offerta non 猫 disponibile",
    "Aceast膬 ofert膬 nu este disponibil膬",
    "Ez az aj谩nlat nem 谩ll rendelkez茅sre",
    "Tato nab铆dka nen铆 k dispozici",
    "Bu teklif kullan谋lam谋yor",
]

SUBSCRIBED_PHRASES = [
    "You're already subscribed",
    "B岷 膽茫 膽膬ng k媒",
    "宸茶闃?",
    "Ya est谩s suscrito",
]

VERIFIED_UNBOUND_PHRASES = [
    "Get student offer",
    "Nh岷璶 瓢u 膽茫i d脿nh cho sinh vi锚n",
    "Obtener oferta para estudiantes",
    "Obter oferta de estudante",
    "鑾峰彇瀛︾敓浼樻儬",
    "鐛插彇瀛哥敓鍎儬",
    "Dapatkan penawaran pelajar",
]


def extract_verification_id(link_or_id: str) -> Optional[str]:
    if not link_or_id:
        return None
    import re

    match_param = re.search(r"verificationId=([a-zA-Z0-9]+)", link_or_id)
    if match_param:
        return match_param.group(1)
    match_path = re.search(r"verify/([a-zA-Z0-9]+)", link_or_id)
    if match_path:
        return match_path.group(1)
    if re.match(r"^[a-zA-Z0-9]+$", link_or_id):
        return link_or_id
    return None


async def detect_google_one_status_dom(
    page: Page,
    timeout_seconds: float = 20.0,
) -> Tuple[str, Optional[str]]:
    """
    Returns:
        ('subscribed' | 'verified' | 'link_ready' | 'ineligible' | 'timeout', link_or_none)
    """
    start = time.time()

    while time.time() - start < timeout_seconds:
        for phrase in SUBSCRIBED_PHRASES:
            try:
                loc = page.locator(f'text="{phrase}"').first
                if await loc.count() > 0 and await loc.is_visible():
                    return "subscribed", None
            except Exception:
                continue

        for phrase in VERIFIED_UNBOUND_PHRASES:
            try:
                loc = page.locator(f'text="{phrase}"').first
                if await loc.count() > 0 and await loc.is_visible():
                    return "verified", None
            except Exception:
                continue

        for phrase in NOT_AVAILABLE_PHRASES:
            try:
                loc = page.locator(f'text="{phrase}"').first
                if await loc.count() > 0 and await loc.is_visible():
                    return "ineligible", None
            except Exception:
                continue

        # 额外兜底：部分页面显示 “isn't eligible / not eligible” 而非 “not available”
        try:
            loc = page.locator('text=/not\\s+eligible|isn.?t\\s+eligible/i').first
            if await loc.count() > 0 and await loc.is_visible():
                return "ineligible", None
        except Exception:
            pass

        link_element = page.locator('a[href*="sheerid.com"]').first
        try:
            if await link_element.count() > 0:
                href = await link_element.get_attribute("href")
                text_content = ""
                try:
                    text_content = (await link_element.inner_text()) or ""
                except Exception:
                    pass

                if text_content.strip():
                    try:
                        from deep_translator import GoogleTranslator

                        translated_text = GoogleTranslator(source="auto", target="en").translate(text_content).lower()
                        if "student offer" in translated_text or "get offer" in translated_text:
                            return "verified", None
                    except Exception:
                        pass

                return "link_ready", href
        except Exception:
            pass

        try:
            await page.wait_for_timeout(1000)
        except Exception:
            pass

    return "timeout", None
