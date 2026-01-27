"""
@file recovery_email_service.py
@brief 修改辅助邮箱服务模块
@details 自动化修改 Google 账号的 Recovery Email
"""
import asyncio
import os
import tempfile
import time
from typing import Tuple, Optional, Callable
from playwright.async_api import async_playwright, Page

from .temp_email import create_temp_email, wait_for_verification_code
from .qq_email import (
    wait_for_google_verification_code as qq_wait_code,
    load_qq_email_config,
    test_qq_email_connection,
    generate_random_email,
    DEFAULT_CUSTOM_DOMAIN,
    DEFAULT_QQ_AUTH_CODE,
    DEFAULT_QQ_EMAIL
)

RECOVERY_EMAIL_URL = "https://myaccount.google.com/recovery/email"

# 调试目录
DEBUG_DIR = os.path.join(tempfile.gettempdir(), "recovery_email_debug")
os.makedirs(DEBUG_DIR, exist_ok=True)


async def _save_debug_info(page: Page, step: str, browser_id: str = ""):
    """保存调试截图和HTML"""
    try:
        timestamp = int(time.time())
        prefix = f"{browser_id[:8]}_" if browser_id else ""
        
        # 保存截图
        png_path = os.path.join(DEBUG_DIR, f"{prefix}{step}_{timestamp}.png")
        await page.screenshot(path=png_path, timeout=10000)
        
        # 保存HTML
        html_path = os.path.join(DEBUG_DIR, f"{prefix}{step}_{timestamp}.html")
        content = await page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        return png_path, html_path
    except Exception as e:
        print(f"[Debug] 保存调试信息失败: {e}")
        return None, None


async def _handle_password_verification(page: Page, account_info: dict, log: Callable) -> bool:
    """处理密码/2FA身份验证"""
    import pyotp
    
    password = account_info.get('password', '')
    secret = (account_info.get('secret') or account_info.get('2fa_secret') or 
              account_info.get('secret_key') or '').replace(' ', '').strip()
    handled = False

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
    
    # 检查是否在密码验证页面
    try:
        # 检测密码输入框
        pwd_input = page.locator('input[type="password"]').first
        if await pwd_input.count() > 0 and await pwd_input.is_visible():
            log("检测到密码验证页面，输入密码...")
            await pwd_input.fill(password)
            await asyncio.sleep(0.5)
            handled = True
            
            # 点击 Next/下一步
            next_selectors = [
                'button:has-text("Next")',
                'button:has-text("下一步")',
                '#passwordNext button',
                'button[type="submit"]',
            ]
            for sel in next_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        log("✅ 已点击下一步")
                        break
                except:
                    continue
            
            await asyncio.sleep(3)
    except Exception as e:
        log(f"密码验证处理: {e}")
    
    # 检查是否需要2FA
    try:
        totp_input = page.locator('input[name="totpPin"], input[type="tel"][autocomplete="one-time-code"]').first
        if await totp_input.count() > 0 and await totp_input.is_visible():
            if secret:
                log("检测到2FA验证，输入验证码...")
                code = pyotp.TOTP(secret).now()
                await totp_input.fill(code)
                await asyncio.sleep(0.5)
                handled = True
                
                # 点击验证
                for sel in ['button:has-text("Next")', 'button:has-text("Verify")', '#totpNext button']:
                    try:
                        btn = page.locator(sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click()
                            log("✅ 已提交2FA")
                            break
                    except:
                        continue
                
                await asyncio.sleep(3)
            else:
                log("⚠️ 需要2FA但未提供密钥")
    except Exception as e:
        log(f"2FA验证处理: {e}")

    return handled


async def _wait_recovery_email_content(page: Page, log: Callable, timeout_s: float = 30.0) -> bool:
    """等待 Recovery email 页面主体内容渲染完成（避免只剩标题/空白页）"""
    try:
        await page.wait_for_function(
            """
            () => {
              const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                return el.getClientRects().length > 0;
              };

              const root = document.querySelector('[data-help-context="RECOVERY_EMAIL_SCREEN"]');
              if (!root || !isVisible(root)) return false;

              const candidates = [
                'button[aria-label*="Edit"]',
                'button[aria-label*="edit"]',
                'button[aria-label*="Verify"]',
                'button[aria-label*="verify"]',
                'h2',
              ];

              for (const sel of candidates) {
                const el = root.querySelector(sel);
                if (isVisible(el)) return true;
              }
              return false;
            }
            """,
            timeout=int(timeout_s * 1000),
        )
        return True
    except Exception:
        log("⚠️ Recovery email 页面内容未渲染完成（可能空白页/加载卡住）")
        return False


async def _settle_page(page: Page, timeout_ms: int = 20000) -> None:
    """尽量等待页面完成导航/渲染（不使用固定 sleep）"""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


async def _wait_after_edit_action(page: Page, timeout_ms: int = 25000) -> None:
    """
    点击“编辑”后等待进入下一状态：
    - 弹出对话框
    - 跳到密码/2FA 验证页
    - Recovery email 页面主体渲染完成
    """
    try:
        await page.wait_for_function(
            """
            () => {
              const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                return el.getClientRects().length > 0;
              };

              const pwd = document.querySelector('input[type="password"]');
              if (isVisible(pwd)) return true;

              const dialog = document.querySelector('[role="dialog"]');
              if (isVisible(dialog)) return true;

              const root = document.querySelector('[data-help-context="RECOVERY_EMAIL_SCREEN"]');
              if (root && isVisible(root)) {
                const el =
                  root.querySelector('input[type="email"]') ||
                  root.querySelector('input[autocomplete="email"]') ||
                  root.querySelector('button[aria-label*="Edit"]') ||
                  root.querySelector('button[aria-label*="edit"]') ||
                  root.querySelector('button[aria-label*="Verify"]') ||
                  root.querySelector('button[aria-label*="verify"]') ||
                  root.querySelector('h2');
                if (isVisible(el)) return true;
              }
              return false;
            }
            """,
            timeout=timeout_ms,
        )
    except Exception:
        pass


async def _ensure_recovery_email_page(page: Page, account_info: dict, log: Callable) -> None:
    """确保回到 Recovery Email 页面（身份验证后可能跳转到 /security 或停留在 accounts.google.com）"""
    auth_attempts = 0
    for _ in range(2):
        try:
            url = (page.url or "").lower()
            if "accounts.google.com" in url or "challenge" in url:
                if auth_attempts >= 1:
                    log("⚠️ 再次触发密码/2FA验证，停止自动重试以避免循环（可能需要人工确认一次）")
                    return
                handled = await _handle_password_verification(page, account_info, log)
                if handled:
                    auth_attempts += 1
                await _settle_page(page, timeout_ms=20000)

            if "recovery/email" in (page.url or "").lower():
                return

            await page.goto(RECOVERY_EMAIL_URL, wait_until="domcontentloaded", timeout=60000)
            await _settle_page(page, timeout_ms=20000)
            if await _wait_recovery_email_content(page, log, timeout_s=20):
                return
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception:
                await page.goto(RECOVERY_EMAIL_URL, wait_until="domcontentloaded", timeout=60000)
            await _settle_page(page, timeout_ms=20000)
            if await _wait_recovery_email_content(page, log, timeout_s=20):
                return
        except Exception:
            await asyncio.sleep(1.5)


def _email_input_selectors() -> list:
    return [
        'input[type="email"]',
        'input[autocomplete="email"]',
        'input[type="text"][aria-label*="email" i]:not([aria-label*="search" i])',
        'input[type="text"][placeholder*="email" i]',
        'input[type="text"][aria-label*="邮箱"]:not([aria-label*="搜索"])',
        'input[type="text"][placeholder*="邮箱"]',
        'input[aria-label*="email" i]:not([aria-label*="search" i])',
        'input[aria-label*="邮箱"]:not([aria-label*="搜索"])',
    ]


async def change_recovery_email(
    page: Page,
    account_info: dict,
    log_callback: Optional[Callable] = None,
    browser_id: str = "",
    use_qq_email: bool = False,
    qq_email: str = "",
    qq_auth_code: str = ""
) -> Tuple[bool, str, Optional[str]]:
    """
    修改 Google 账号的辅助邮箱
    @param page Playwright 页面对象
    @param account_info 账号信息 {'email', 'password', 'secret', ...}
    @param log_callback 日志回调
    @param browser_id 浏览器ID（用于调试文件命名）
    @param use_qq_email 是否使用QQ邮箱接收验证码
    @param qq_email QQ邮箱地址（use_qq_email=True时必须）
    @param qq_auth_code QQ邮箱授权码（use_qq_email=True时必须）
    @return (success, message, new_recovery_email)
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(f"[RecoveryEmail] {msg}")
    
    async def fail_with_debug(step: str, message: str):
        """失败时保存调试信息"""
        png, html = await _save_debug_info(page, step, browser_id)
        if png:
            log(f"📸 调试截图: {png}")
        if html:
            log(f"📄 调试HTML: {html}")
        return False, message, None
    
    try:
        # Step 1: 准备接收邮箱
        jwt = None  # 临时邮箱的JWT token
        new_email = None
        
        if use_qq_email:
            # 使用QQ邮箱接收验证码（通过自定义域名catch-all转发）
            if not qq_email or not qq_auth_code:
                # 尝试从配置文件加载
                qq_email, qq_auth_code = load_qq_email_config()
            
            if not qq_email or not qq_auth_code:
                return False, "未配置QQ邮箱，请先设置QQ邮箱和授权码", None
            
            log("步骤1: 生成自定义域名邮箱...")
            # 测试连接
            success, msg = test_qq_email_connection(qq_email, qq_auth_code)
            if not success:
                return False, f"QQ邮箱连接失败: {msg}", None
            
            # 生成随机的自定义域名邮箱（验证码会转发到QQ邮箱）
            new_email = generate_random_email()
            log(f"✅ 生成邮箱: {new_email} (验证码转发到 {qq_email})")
        else:
            # 使用临时邮箱
            log("步骤1: 创建临时邮箱...")
            jwt, new_email = create_temp_email()
            if not jwt or not new_email:
                return False, "创建临时邮箱失败", None
            log(f"✅ 临时邮箱: {new_email}")
        
        # Step 2: 导航到辅助邮箱页面
        log("步骤2: 导航到辅助邮箱设置页...")
        await page.goto(RECOVERY_EMAIL_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        
        # Step 3: 确保已登录
        from .google_auth import ensure_google_login
        
        # 检查是否跳转到登录页
        if "accounts.google.com" in page.url and "recovery/email" not in page.url:
            log("步骤3: 需要登录，正在登录...")
            success, msg = await ensure_google_login(page, account_info)
            if not success:
                return await fail_with_debug("step3_login_failed", f"登录失败: {msg}")
            # 重新导航
            await page.goto(RECOVERY_EMAIL_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)
        else:
            log("步骤3: 已登录，无需重新登录")
        
        # 等待页面加载
        await asyncio.sleep(2)
        
        # Step 3.5: 处理身份验证（Google可能要求输入密码确认身份）
        pwd_visible = await page.locator('input[type="password"]').count() > 0
        if pwd_visible:
            log("步骤3.5: Google要求身份验证，输入密码...")
        await _handle_password_verification(page, account_info, log)
        await asyncio.sleep(2)
        
        # 确认现在在 recovery/email 页面
        if "recovery/email" not in page.url:
            # 可能需要重新导航
            await page.goto(RECOVERY_EMAIL_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)
            await _handle_password_verification(page, account_info, log)
            await asyncio.sleep(2)
        await _ensure_recovery_email_page(page, account_info, log)
        
        # Step 4: 点击编辑按钮（铅笔图标）
        log("步骤4: 点击编辑按钮...")
        edit_clicked = False
        retried_after_auth = False

        # 先等页面主体渲染出来（避免空白页时误判找不到按钮）
        await _wait_recovery_email_content(page, log, timeout_s=30)
        
        async def _click_edit_and_wait_dialog(btn, log_prefix: str) -> bool:
            """点击编辑按钮并等待对话框出现，返回是否成功"""
            try:
                # 使用 force=True 绕过可能的遮挡物（如插件 overlay）
                await btn.click(force=True)
                await asyncio.sleep(1)
                
                # 显式等待对话框出现
                for _ in range(15):  # 最多等15秒
                    try:
                        dialog = page.locator('[role="dialog"]')
                        if await dialog.count() > 0:
                            # 检查是否有可见的对话框
                            for i in range(min(await dialog.count(), 5)):
                                d = dialog.nth(i)
                                if await d.is_visible():
                                    log(f"✅ {log_prefix} - 对话框已打开")
                                    return True
                    except Exception:
                        pass
                    
                    # 也检查是否跳转到密码验证页
                    try:
                        pwd_input = page.locator('input[type="password"]')
                        if await pwd_input.count() > 0 and await pwd_input.is_visible():
                            log(f"✅ {log_prefix} - 跳转到密码验证页")
                            return True
                    except Exception:
                        pass
                    
                    await asyncio.sleep(1)
                
                log(f"⚠️ {log_prefix} - 点击后对话框未出现")
                return False
            except Exception as e:
                log(f"⚠️ {log_prefix} 失败: {e}")
                return False

        # 首先尝试在 "Your recovery email" 卡片区域内找编辑按钮
        card_selectors = [
            'div:has-text("Your recovery email")',
            'div:has-text("recovery email")',
            '[data-settingid*="RECOVERY"]',
        ]
        
        for card_sel in card_selectors:
            if edit_clicked:
                break
            try:
                card = page.locator(card_sel).first
                if await card.count() > 0:
                    # 在卡片内找编辑按钮 - 优先使用 aria-label
                    edit_btn = card.locator('button[aria-label*="Edit"], button[aria-label*="edit"]').first
                    if await edit_btn.count() > 0 and await edit_btn.is_visible():
                        if await _click_edit_and_wait_dialog(edit_btn, "点击编辑按钮 (卡片内 aria-label)"):
                            edit_clicked = True
                            break
                    # 备选：找带 svg 的按钮
                    edit_btn = card.locator('button:has(svg)').first
                    if await edit_btn.count() > 0 and await edit_btn.is_visible():
                        if await _click_edit_and_wait_dialog(edit_btn, "点击编辑按钮 (卡片内 svg)"):
                            edit_clicked = True
                            break
            except Exception:
                continue
        
        # 备选：直接查找带有 Edit aria-label 的按钮
        if not edit_clicked:
            edit_selectors = [
                'button[aria-label*="Edit recovery"]',
                'button[aria-label*="Edit"]',
                'button[aria-label*="edit"]',
                '[role="button"][aria-label*="Edit"]',
            ]
            
            for selector in edit_selectors:
                try:
                    locator = page.locator(selector).first
                    if await locator.count() > 0 and await locator.is_visible():
                        if await _click_edit_and_wait_dialog(locator, f"点击编辑按钮 ({selector})"):
                            edit_clicked = True
                            break
                except Exception:
                    continue
        
        if not edit_clicked:
            return await fail_with_debug("step4_edit_button", "未找到编辑按钮或点击后对话框未打开")

        # 点击编辑后可能跳转到“验证身份/输入密码”流程
        await _settle_page(page, timeout_ms=25000)
        await _handle_password_verification(page, account_info, log)
        await asyncio.sleep(1)

        # Step 5: 输入新邮箱（对话框或页面内编辑）
        log("步骤5: 输入新辅助邮箱...")

        # 若验证后出现空白页，先等待渲染；必要时刷新
        if not await _wait_recovery_email_content(page, log, timeout_s=20):
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception:
                await page.goto(RECOVERY_EMAIL_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2.5)
            await _wait_recovery_email_content(page, log, timeout_s=20)

        root = page.locator('[data-help-context="RECOVERY_EMAIL_SCREEN"]').first
        try:
            if await root.count() == 0 or not await root.is_visible():
                root = page.locator("body")
        except Exception:
            root = page.locator("body")

        async def find_email_input():
            try:
                import re

                # 可能存在多个 dialog（有的隐藏），不能直接取 .first
                dialogs = page.locator('[role="dialog"]').filter(
                    has_text=re.compile(r"set up recovery email|recovery email|辅助邮箱|恢复邮箱", re.I)
                )
                if await dialogs.count() == 0:
                    dialogs = page.locator('[role="dialog"]')

                visible_dialog = None
                count = min(await dialogs.count(), 6)
                for i in range(count):
                    d = dialogs.nth(i)
                    try:
                        if await d.is_visible():
                            visible_dialog = d
                            break
                    except Exception:
                        continue

                if visible_dialog is not None:
                    # 弹窗内优先用宽泛 selector：该输入框经常没有 aria-label/placeholder/type=email
                    dialog_candidates = [
                        'input[type="email"]',
                        'input[aria-label*="recovery" i]',
                        'input[placeholder*="email" i]',
                        'input[autocomplete="email"]',
                        'input[type="text"]',
                        'textarea',
                        'input:not([type="hidden"])',
                    ]
                    for sel in dialog_candidates:
                        loc = visible_dialog.locator(sel).first
                        if await loc.count() > 0:
                            try:
                                await loc.wait_for(state="visible", timeout=3000)
                            except Exception:
                                pass
                            try:
                                if await loc.is_visible():
                                    return loc
                            except Exception:
                                return loc
            except Exception:
                pass

            for sel in _email_input_selectors():
                try:
                    loc = root.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        return loc
                except Exception:
                    continue
            return None

        email_input = await find_email_input()

        # 常见情况：验证后回到页面，但编辑态未打开；重试点击一次编辑按钮
        if not email_input and not retried_after_auth:
            retried_after_auth = True
            log("⚠️ 未找到邮箱输入框，尝试重新点击编辑按钮...")
            try:
                locator = page.locator(
                    'button[aria-label*="Edit recovery"], button[aria-label*="Edit"], button[aria-label*="edit"]'
                ).first
                if await locator.count() > 0 and await locator.is_visible():
                    await locator.click()
                    await _settle_page(page, timeout_ms=25000)
                    await _wait_after_edit_action(page, timeout_ms=25000)
                    await _handle_password_verification(page, account_info, log)
                    await _settle_page(page, timeout_ms=25000)
                    await _ensure_recovery_email_page(page, account_info, log)
            except Exception:
                pass
            email_input = await find_email_input()

        if not email_input:
            return await fail_with_debug("step5_email_input", "未找到邮箱输入框（可能仍停留在验证密码/安全检查页面）")
        
        # 清空并输入新邮箱
        await email_input.click()
        await email_input.fill("")  # 清空
        await asyncio.sleep(0.3)
        await email_input.fill(new_email)
        log(f"✅ 已输入新邮箱: {new_email}")
        await asyncio.sleep(1)
        
        # Step 6: 点击 Save 按钮
        log("步骤6: 点击 Save 按钮...")
        save_clicked = False
        
        save_selectors = [
            '[role="dialog"] button:has-text("Save")',
            '[role="dialog"] button:has-text("保存")',
            'button:has-text("Save")',
            'button:has-text("保存")',
            '[role="button"]:has-text("Save")',
        ]
        
        for selector in save_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    await locator.click()
                    save_clicked = True
                    log("✅ 点击 Save 成功")
                    break
            except Exception:
                continue
        
        if not save_clicked:
            return await fail_with_debug("step6_save_button", "未找到 Save 按钮")
        
        await asyncio.sleep(3)
        
        # Step 7: 等待验证码对话框并输入验证码
        log("步骤7: 等待验证码...")
        
        # 等待验证码对话框出现
        verify_dialog = False
        for _ in range(10):
            try:
                if await page.locator('text="Verify your recovery email"').count() > 0:
                    verify_dialog = True
                    break
                if await page.locator('text="Verification code"').count() > 0:
                    verify_dialog = True
                    break
            except:
                pass
            await asyncio.sleep(0.5)
        
        if not verify_dialog:
            # 检查是否已经成功（无需验证）
            try:
                if await page.locator(f'text="{new_email}"').count() > 0:
                    log("✅ 辅助邮箱已更新（无需验证）")
                    return True, "辅助邮箱修改成功", new_email
            except:
                pass
            return await fail_with_debug("step7_verify_dialog", "未出现验证码对话框")
        
        # 获取验证码
        code = None
        if use_qq_email:
            # 从QQ邮箱获取验证码（根据目标邮箱过滤，支持并发）
            log(f"从QQ邮箱获取验证码 (目标: {new_email})...")
            success, result = qq_wait_code(
                qq_email=qq_email,
                auth_code=qq_auth_code,
                target_email=new_email,  # 传入目标邮箱用于过滤
                timeout_seconds=120,
                poll_interval=5,
                log_callback=log
            )
            if success:
                code = result
            else:
                log(f"⚠️ QQ邮箱获取验证码失败: {result}")
        else:
            # 从临时邮箱获取验证码
            log("从临时邮箱获取验证码...")
            code = wait_for_verification_code(jwt, timeout=120, poll_interval=5, log_callback=log)
        
        if not code:
            return await fail_with_debug("step7_code_timeout", "获取验证码超时")
        
        # Step 8: 输入验证码
        log(f"步骤8: 输入验证码 {code}...")
        
        # 查找验证码输入框
        code_input = None
        code_selectors = [
            '[role="dialog"] input[type="text"]',
            '[role="dialog"] input[type="tel"]',
            '[role="dialog"] input',
            'input[aria-label*="code"]',
            'input[aria-label*="验证码"]',
            'input[placeholder*="code"]',
        ]
        
        for selector in code_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    code_input = locator
                    break
            except Exception:
                continue
        
        if not code_input:
            return await fail_with_debug("step8_code_input", "未找到验证码输入框")
        
        await code_input.fill(code)
        log("✅ 已输入验证码")
        await asyncio.sleep(1)
        
        # Step 9: 点击 Verify 按钮
        log("步骤9: 点击 Verify 按钮...")
        verify_clicked = False
        
        verify_selectors = [
            '[role="dialog"] button:has-text("Verify")',
            '[role="dialog"] button:has-text("验证")',
            'button:has-text("Verify")',
            'button:has-text("验证")',
            '[role="button"]:has-text("Verify")',
        ]
        
        for selector in verify_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    await locator.click()
                    verify_clicked = True
                    log("✅ 点击 Verify 成功")
                    break
            except Exception:
                continue
        
        if not verify_clicked:
            return await fail_with_debug("step9_verify_button", "未找到 Verify 按钮")
        
        await asyncio.sleep(3)
        
        # Step 10: 检查是否成功
        log("步骤10: 检查修改结果...")
        
        # 检查页面是否显示新邮箱
        try:
            for _ in range(10):
                if await page.locator(f'text="{new_email}"').count() > 0:
                    log("✅ 辅助邮箱修改成功")
                    return True, "辅助邮箱修改成功", new_email
                await asyncio.sleep(0.5)
        except:
            pass
        
        # 检查是否有错误提示
        try:
            error_texts = await page.locator('[role="alert"], .error, [class*="error"]').all_inner_texts()
            if error_texts:
                return False, f"修改失败: {error_texts[0][:100]}", None
        except:
            pass
        
        log("✅ 辅助邮箱修改完成（验证通过）")
        return True, "辅助邮箱修改完成", new_email
        
    except Exception as e:
        log(f"❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        return False, f"异常: {str(e)}", None


def process_change_recovery_email(
    browser_id: str,
    log_callback: Optional[Callable] = None,
    close_after: bool = True,
    use_qq_email: bool = False,
    qq_email: str = "",
    qq_auth_code: str = ""
) -> Tuple[bool, str, Optional[str]]:
    """
    处理单个浏览器的辅助邮箱修改
    @param browser_id 浏览器ID
    @param log_callback 日志回调
    @param close_after 完成后是否关闭浏览器
    @param use_qq_email 是否使用QQ邮箱接收验证码
    @param qq_email QQ邮箱地址
    @param qq_auth_code QQ邮箱授权码
    @return (success, message, new_email)
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    
    log("打开浏览器...")
    
    try:
        from core.bit_api import open_browser, close_browser
        from core.database import DBManager
    except ImportError as e:
        return False, f"导入失败: {e}", None
    
    # 获取账号信息
    account_info = None
    email = None
    try:
        row = DBManager.get_account_by_browser_id(browser_id)
        if row:
            recovery = row.get('recovery_email') or ''
            secret = row.get('secret_key') or ''
            email = row.get('email') or ''
            account_info = {
                'email': email,
                'password': row.get('password') or '',
                'backup': recovery,
                'backup_email': recovery,
                'secret': secret,
                '2fa_secret': secret
            }
    except Exception as e:
        log(f"获取账号信息失败: {e}")
    
    if not account_info:
        return False, "未找到账号信息", None
    
    # 打开浏览器
    result = open_browser(browser_id)
    if not result.get('success'):
        return False, f"打开浏览器失败: {result.get('msg', '未知错误')}", None
    
    ws_endpoint = result['data']['ws']
    
    async def _run():
        async with async_playwright() as playwright:
            try:
                browser = await playwright.chromium.connect_over_cdp(ws_endpoint)
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else await context.new_page()
                
                success, msg, new_email = await change_recovery_email(
                    page, account_info, log, browser_id,
                    use_qq_email=use_qq_email,
                    qq_email=qq_email,
                    qq_auth_code=qq_auth_code
                )
                
                # 更新数据库
                if success and new_email and email:
                    try:
                        DBManager.update_account_recovery_email(email, new_email)
                        log(f"✅ 数据库已更新: {new_email}")
                    except Exception as e:
                        log(f"数据库更新失败: {e}")
                
                return success, msg, new_email
                
            except Exception as e:
                return False, str(e), None
    
    try:
        result = asyncio.run(_run())
    finally:
        if close_after:
            try:
                close_browser(browser_id)
            except Exception:
                pass
    
    return result
