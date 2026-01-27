"""
@file google_auth.py
@brief Google账号认证和登录状态检测模块 (V2)
@details 包含Google账号登录状态检测(头像检测)、自动登录、资格检测(API拦截)等功能
@author Auto System
@date 2026-01-22
"""

import asyncio
import time
import re
import pyotp
from typing import Tuple, Optional, Dict, Any
from playwright.async_api import Page, expect
from .google_recovery import handle_recovery_email_challenge, detect_manual_verification

# ==================== 登录状态枚举 ====================
class GoogleLoginStatus:
    """Google登录状态枚举"""
    LOGGED_IN = "logged_in"           # 已登录
    NOT_LOGGED_IN = "not_logged_in"   # 未登录（在登录页面）
    # 以下状态在V2检测中可能归类为NOT_LOGGED_IN，但保留枚举兼容
    NEED_PASSWORD = "need_password"   
    NEED_2FA = "need_2fa"             
    NEED_RECOVERY = "need_recovery"   
    SESSION_EXPIRED = "session_expired"
    SECURITY_CHECK = "security_check" 
    UNKNOWN = "unknown"               


# ==================== V2 检测逻辑 (核心) ====================

async def check_google_login_by_avatar(page: Page, timeout: float = 10.0) -> bool:
    """
    @brief 核心登录检测：通过检测头像按钮判断是否已登录
    @param page Playwright 页面对象
    @param timeout 超时时间(秒)
    @return True=已登录, False=未登录
    """
    try:
        # 如果不在Google域下，可能需要导航（取决于调用者，这里假设已在Google页面）
        # 如果页面是空白或 about:blank，导航到 accounts.google.com
        if 'about:blank' in page.url:
            await page.goto("https://accounts.google.com/", wait_until="domcontentloaded")

        # 登录页有输入框 => 未登录（对齐 bitbrowser-automation 判定逻辑）
        try:
            email_box = page.locator('input[type="email"]').first
            if await email_box.count() > 0 and await email_box.is_visible():
                return False
        except Exception:
            pass
        try:
            pwd_box = page.locator('input[type="password"]').first
            if await pwd_box.count() > 0 and await pwd_box.is_visible():
                return False
        except Exception:
            pass

        # 头像按钮选择器 (多个备选)
        avatar_selectors = [
            'a[aria-label*="Google Account"] img.gbii',
            'a.gb_B[role="button"] img',
            'a[href*="SignOutOptions"] img',
            'img.gb_Q.gbii',
            'a[aria-label*="Google 帐号"] img',
            'a[aria-label*="Google 账号"] img'
        ]
        
        # 尝试检测头像元素
        # 使用first匹配，any即可
        for selector in avatar_selectors:
            try:
                # 使用 expect 自动等待，设置较短超时避免所有都check一遍花太久，
                # 但首个check需要足够时间等待页面加载
                # 这里逻辑优化：并行的逻辑比较难写，顺序检查
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                     return True
            except:
                continue
                
        # 如果上面快速检查没过，使用 expect 等待其中一个通用选择器（等待页面加载延迟）
        try:
            primary_selector = 'a[aria-label*="Google"] img'
            await expect(page.locator(primary_selector).first).to_be_visible(timeout=timeout * 1000)
            return True
        except:
            pass

        return False
        
    except Exception as e:
        print(f"[GoogleAuth] 登录检测异常: {e}")
        return False


async def check_google_login_status(page: Page, timeout: float = 5.0) -> Tuple[str, Dict[str, Any]]:
    """
    @brief 兼容旧接口：检测登录状态
    @return (status, extra_info)
    """
    is_logged = await check_google_login_by_avatar(page, timeout)
    if is_logged:
        # 尝试获取邮箱（可选）
        email = await _extract_logged_in_email(page)
        return GoogleLoginStatus.LOGGED_IN, {'email': email} if email else {}
    else:
        return GoogleLoginStatus.NOT_LOGGED_IN, {}


async def check_google_one_status(
    page: Page, 
    timeout: float = 20.0
) -> Tuple[str, Optional[str]]:
    """
    @brief V2资格检测：通过 API 拦截 + jsname 属性检测资格状态
    @param page Playwright 页面对象
    @param timeout 超时时间(秒)
    @return (status, sheerid_link)
            status: 'subscribed_antigravity' | 'subscribed' | 'verified' | 'link_ready' | 'ineligible' | 'error'
    """
    api_response_data = None
    response_received = asyncio.Event()
    
    async def handle_response(response):
        """响应拦截处理"""
        nonlocal api_response_data
        try:
            # 关键特征 rpcids=GI6Jdd
            if 'rpcids=GI6Jdd' in response.url:
                text = await response.text()
                api_response_data = text
                response_received.set()
                # print(f"[GoogleAuth] 🔍 拦截到 GI6Jdd API 响应")
        except Exception:
            pass
    
    # 注册响应监听器
    page.on("response", handle_response)
    
    try:
        # 导航到目标页面（如果不在的话）
        target_url = "https://one.google.com/ai-student?g1_landing_page=75"
        if target_url not in page.url:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout * 1000)
        
        # 等待 API 响应 (最多 timeout 秒)
        try:
            await asyncio.wait_for(response_received.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass # 超时没收到API，继续检查元素
        
        # 等待页面网络空闲（确保元素加载）
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except:
            pass
        
        # ============ 分析 API 响应 ============
        if api_response_data:
            status = _parse_api_response(api_response_data)
            if status:
                return status, None
        
        # ============ 检测页面元素 (API没拦截到或API显示未订阅时) ============
        return await _detect_page_elements(page)
        
    except Exception as e:
        print(f"[GoogleAuth] 资格检测异常: {e}")
        return 'error', str(e)
        
    finally:
        # 移除监听器
        page.remove_listener("response", handle_response)


# ==================== 辅助函数 ====================

def _parse_api_response(response_text: str) -> Optional[str]:
    """解析 GI6Jdd API 响应"""
    try:
        # 检查订阅状态
        # 响应通常包含 JSON 数组，这里简化做字符串匹配
        has_2tb = '2 TB' in response_text or '2TB' in response_text or '"2 TB"' in response_text
        has_antigravity = 'Antigravity' in response_text or '"Antigravity"' in response_text
        
        if has_2tb:
            if has_antigravity:
                return 'subscribed_antigravity'
            else:
                return 'subscribed'
        return None
    except Exception:
        return None


async def _detect_page_elements(page: Page) -> Tuple[str, Optional[str]]:
    """通过页面元素检测资格状态"""
    try:
        # 1. 检查 hSRGPd (有资格待验证 - 含有 SheerID 验证链接)
        link_ready_locator = page.locator('[jsname="hSRGPd"]')
        if await link_ready_locator.count() > 0 and await link_ready_locator.first.is_visible():
            sheerid_link = await _extract_sheerid_link(page)
            return 'link_ready', sheerid_link
        
        # 2. 检查 V67aGc (已验证未绑卡 - Get student offer 按钮)
        verified_locator = page.locator('[jsname="V67aGc"]')
        if await verified_locator.count() > 0 and await verified_locator.first.is_visible():
            return 'verified', None
        
        # 3. 再次检查是否有 SheerID 链接 (备选方案 - 有时候jsname可能变)
        sheerid_link = await _extract_sheerid_link(page)
        if sheerid_link:
            return 'link_ready', sheerid_link
        
        # 4. 检查是否有 "Get student offer" 相关按钮
        offer_selectors = [
            'button:has-text("Get student offer")',
            'button:has-text("Get offer")',
            '[data-action="offerDetails"]',
        ]
        for selector in offer_selectors:
             if await page.locator(selector).count() > 0:
                  return 'verified', None

        # 5. 再次检查已订阅文本（防止API漏掉）
        if await page.locator('text="Subscribed"').count() > 0 or await page.locator('text="已订阅"').count() > 0:
             return 'subscribed', None

        # 6. 已订阅页面文案（参考 bit 项目：You're already subscribed / Manage plan）
        try:
            if await page.locator('text=/already\\s+subscribed/i').count() > 0:
                return 'subscribed', None
        except Exception:
            pass

        return 'ineligible', None
        
    except Exception:
        return 'ineligible', None


async def _extract_sheerid_link(page: Page) -> Optional[str]:
    """提取 SheerID 验证链接"""
    try:
        # 方法1: 查找 sheerid.com 链接
        sheerid_locator = page.locator('a[href*="sheerid.com"]')
        if await sheerid_locator.count() > 0:
            href = await sheerid_locator.first.get_attribute("href")
            if href:
                return href
        
        # 方法2: 从页面内容中查找
        content = await page.content()
        match = re.search(r'https://[^"\']*sheerid\.com[^"\']*', content)
        if match:
            return match.group(0)
        return None
    except Exception:
        return None


async def _extract_logged_in_email(page: Page) -> Optional[str]:
    """提取已登录邮箱"""
    try:
        # 尝试从aria-label提取: "Google Account: Name  (email@gmail.com)"
        label_locator = page.locator('a[aria-label*="Google"]').first
        if await label_locator.count() > 0:
            label = await label_locator.get_attribute('aria-label') or ""
            match = re.search(r'[\w\.-]+@[\w\.-]+', label)
            if match:
                return match.group(0)
    except:
        pass
    return None


# ==================== 登录操作逻辑 (保持) ====================

async def is_logged_in(page: Page) -> bool:
    """检查是否已登录"""
    return await check_google_login_by_avatar(page)

async def _dismiss_post_login_prompts(page: Page) -> bool:
    """处理登录后可能出现的安全/Passkeys 提示（Not now/Cancel/No thanks 等）"""
    # 复用 bitbrowser-automation 的“多语言 Skip/Not now”思路：
    # - 先用多选择器快速点击
    # - 再用 get_by_role + regex 兜底
    selectors = [
        'button:has-text("Not now")',
        '[role="button"]:has-text("Not now")',
        'button:has-text("No thanks")',
        '[role="button"]:has-text("No thanks")',
        'button:has-text("Cancel")',
        '[role="button"]:has-text("Cancel")',
        'button:has-text("Later")',
        '[role="button"]:has-text("Later")',
        'button:has-text("Skip")',
        '[role="button"]:has-text("Skip")',
        'button:has-text("Omitir")',
        '[role="button"]:has-text("Omitir")',
        'button:has-text("Overslaan")',
        '[role="button"]:has-text("Overslaan")',
        'button:has-text("暂不")',
        '[role="button"]:has-text("暂不")',
        'button:has-text("取消")',
        '[role="button"]:has-text("取消")',
        'button:has-text("稍后")',
        '[role="button"]:has-text("稍后")',
        'button:has-text("跳过")',
        '[role="button"]:has-text("跳过")',
    ]

    for selector in selectors:
        try:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                await btn.click(force=True)
                await asyncio.sleep(1)
                return True
        except Exception:
            continue

    try:
        pattern = re.compile(r"Skip|Omitir|Overslaan|Not now|Later|No thanks|Cancel|暂不|取消|稍后|跳过", re.I)
        btn = page.get_by_role("button", name=pattern).first
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click(force=True)
            await asyncio.sleep(1)
            return True
    except Exception:
        pass

    return False


async def _confirm_logged_in(page: Page, timeout: float = 10.0) -> bool:
    """通过跳转到 myaccount 再检测头像，确认是否真正完成登录"""
    try:
        await page.goto("https://myaccount.google.com/", wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    try:
        if await check_google_login_by_avatar(page, timeout=timeout):
            return True
    except Exception:
        pass
    try:
        url = (page.url or "").lower()
        if "myaccount.google.com" in url and "accounts.google.com" not in url:
            email_box = page.locator('input[type="email"]').first
            pwd_box = page.locator('input[type="password"]').first
            if await email_box.count() == 0 and await pwd_box.count() == 0:
                return True
    except Exception:
        pass
    return False


async def ensure_google_login(page: Page, account_info: dict) -> Tuple[bool, str]:
    """
    确保 Google 已登录（复用 bitbrowser-automation 的判定方式）：
    - 若能看到邮箱输入框 => 需要登录
    - 看不到邮箱输入框 => 视为已登录（继续后续流程）
    """
    async def _has_login_inputs() -> bool:
        try:
            email_box = page.locator('input[type="email"]').first
            if await email_box.count() > 0 and await email_box.is_visible():
                return True
        except Exception:
            pass
        try:
            pwd_box = page.locator('input[type="password"]').first
            if await pwd_box.count() > 0 and await pwd_box.is_visible():
                return True
        except Exception:
            pass
        return False

    # 先处理可能的登录后提示（否则可能遮挡头像导致误判）
    try:
        for _ in range(3):
            if not await _dismiss_post_login_prompts(page):
                break
    except Exception:
        pass

    # 当前页已登录：快速返回（不强制跳转到 accounts.google.com 触发重登）
    try:
        if await check_google_login_by_avatar(page, timeout=6):
            return True, "已登录"
    except Exception:
        pass
    try:
        url = (page.url or "").lower()
        if "myaccount.google.com" in url and "accounts.google.com" not in url and not await _has_login_inputs():
            return True, "已登录"
    except Exception:
        pass

    # 通过跳转 myaccount 判断是否被重定向到登录页
    try:
        await page.goto("https://myaccount.google.com/", wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass
    try:
        for _ in range(3):
            if not await _dismiss_post_login_prompts(page):
                break
    except Exception:
        pass
    try:
        url = (page.url or "").lower()
        if "accounts.google.com" not in url and "myaccount.google.com" in url and not await _has_login_inputs():
            return True, "已登录"
    except Exception:
        pass

    # 未登录：进入登录页并执行登录
    try:
        if "accounts.google.com" not in (page.url or "").lower():
            await page.goto("https://accounts.google.com/", wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass
    try:
        ok, msg = await google_login(page, account_info)
        if ok:
            return True, msg
    except Exception:
        pass

    if await _confirm_logged_in(page, timeout=8):
        return True, "已登录"

    return False, "未检测到已登录且无法进入登录页"


async def google_login(page: Page, account_info: dict) -> Tuple[bool, str]:
    """执行登录流程（复用 bitbrowser-automation 的流程与选择器）"""
    email = (account_info.get("email") or "").strip()
    password = account_info.get("password") or ""
    secret = (account_info.get("secret") or account_info.get("2fa_secret") or account_info.get("secret_key") or "").replace(" ", "").strip()
    backup = (account_info.get("backup") or account_info.get("backup_email") or account_info.get("recovery_email") or "").strip()

    try:
        async def _after_password_submitted() -> Tuple[bool, str]:
            try:
                totp_input = await page.wait_for_selector(
                    'input[name="totpPin"], input[id="totpPin"], input[type="tel"]',
                    timeout=10000,
                )
                if totp_input:
                    if secret:
                        code = pyotp.TOTP(secret).now()
                        await totp_input.fill(code)
                        await page.click("#totpNext >> button")
                    else:
                        handled = await handle_recovery_email_challenge(page, backup)
                        if not handled:
                            return False, "需要2FA或辅助邮箱验证，但未提供secret"
            except Exception:
                pass

            try:
                await handle_recovery_email_challenge(page, backup)
                if await detect_manual_verification(page):
                    return False, "需要人工完成验证码"
            except Exception:
                pass

            await asyncio.sleep(2)
            try:
                for _ in range(5):
                    dismissed = await _dismiss_post_login_prompts(page)
                    if dismissed:
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=5000)
                        except Exception:
                            pass
                    if await check_google_login_by_avatar(page, timeout=6):
                        return True, "登录成功"
                    await asyncio.sleep(1)
            except Exception:
                pass

            if await _confirm_logged_in(page, timeout=10):
                return True, "登录成功"
            return False, "登录后未确认成功"

        # 尽量进入统一入口页面
        try:
            if "accounts.google.com" not in page.url:
                await page.goto("https://accounts.google.com/", wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass

        # 先处理可能的登录后提示；若已登录直接返回
        try:
            for _ in range(3):
                if not await _dismiss_post_login_prompts(page):
                    break
        except Exception:
            pass

        if await check_google_login_by_avatar(page, timeout=6):
            return True, "已登录"

        if not email or not password:
            return False, "需要登录但未提供账号信息"

        # 兼容“验证身份/confirmidentifier”页：先点击下一步进入密码页
        try:
            if "confirmidentifier" in (page.url or "").lower():
                next_loc = page.locator(
                    '#identifierNext >> button, button:has-text("Next"), button:has-text("下一步"), '
                    '[role="button"]:has-text("Next"), [role="button"]:has-text("下一步"), button[type="submit"]'
                ).first
                if await next_loc.count() > 0 and await next_loc.is_visible():
                    await next_loc.click(force=True)
                    await asyncio.sleep(2)
        except Exception:
            pass

        # 若直接出现密码输入框（重登/确认身份流程），无需填邮箱
        try:
            pwd_loc = page.locator('input[type="password"]').first
            if await pwd_loc.count() > 0 and await pwd_loc.is_visible():
                await pwd_loc.fill(password)
                try:
                    btn = page.locator('#passwordNext >> button, button[type="submit"]').first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                    else:
                        await pwd_loc.press("Enter")
                except Exception:
                    try:
                        await pwd_loc.press("Enter")
                    except Exception:
                        pass
                return await _after_password_submitted()
        except Exception:
            pass

        # 常规登录：邮箱 + 密码
        email_input = await page.wait_for_selector('input[type="email"]', timeout=5000)
        if email_input:
            await email_input.fill(email)
            await page.click("#identifierNext >> button")

            await page.wait_for_selector('input[type="password"]', state="visible", timeout=15000)
            await page.fill('input[type="password"]', password)
            await page.click("#passwordNext >> button")
            return await _after_password_submitted()

    except Exception:
        # 不要盲目返回“已登录”：先尝试处理提示并确认
        try:
            for _ in range(3):
                if not await _dismiss_post_login_prompts(page):
                    break
        except Exception:
            pass
        if await _confirm_logged_in(page, timeout=8):
            return True, "已登录"
        return False, "登录流程异常"

    # 未看到邮箱输入框：要么已登录，要么卡在挑战/提示页
    try:
        for _ in range(3):
            if not await _dismiss_post_login_prompts(page):
                break
    except Exception:
        pass

    if await _confirm_logged_in(page, timeout=8):
        return True, "已登录"

    return False, "未找到登录入口或需要人工处理"

# ==================== 综合检测流程 ====================

async def full_google_detection(
    page: Page,
    account_info: dict = None,
    timeout: float = 20.0
) -> Tuple[bool, str, Optional[str]]:
    """
    @brief 完整的 Google 检测流程 (登录 + 资格)
    @return (is_logged_in, status, sheerid_link)
    """
    # 1. 检测登录状态
    is_logged_in = await check_google_login_by_avatar(page, timeout=timeout)
    
    if not is_logged_in:
        return False, 'not_logged_in', None
    
    # 2. 检测资格状态
    status, sheerid_link = await check_google_one_status(page, timeout=timeout)
    
    return True, status, sheerid_link


# ==================== 状态常量 ====================

# 账号状态定义
STATUS_NOT_LOGGED_IN = 'not_logged_in'
STATUS_SUBSCRIBED_ANTIGRAVITY = 'subscribed_antigravity'
STATUS_SUBSCRIBED = 'subscribed'
STATUS_VERIFIED = 'verified'
STATUS_LINK_READY = 'link_ready'
STATUS_INELIGIBLE = 'ineligible'
STATUS_ERROR = 'error'
STATUS_PENDING = 'pending_check'

# 状态显示映射
STATUS_DISPLAY = {
    STATUS_PENDING: '❔待检测',
    STATUS_NOT_LOGGED_IN: '🔒未登录',
    STATUS_INELIGIBLE: '❌无资格',
    STATUS_LINK_READY: '🔗待验证',
    STATUS_VERIFIED: '✅已验证',
    STATUS_SUBSCRIBED: '👑已订阅',
    STATUS_SUBSCRIBED_ANTIGRAVITY: '🌟已解锁',
    STATUS_ERROR: '⚠️错误',
}
