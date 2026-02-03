"""
@file bind_card_service.py
@brief 绑卡订阅服务模块
@details 自动绑定测试卡并完成Google One订阅
"""
import asyncio
import re
import time
from typing import Tuple, Optional, Callable
from playwright.async_api import async_playwright, Page


def _normalize_exp_parts(exp_month: str, exp_year: str) -> Tuple[str, str]:
    raw_month = (exp_month or "").strip()
    raw_year = (exp_year or "").strip()

    if not raw_year and raw_month:
        m = re.search(r"(\d{1,2})\s*[/\-]\s*(\d{2,4})", raw_month)
        if m:
            raw_month, raw_year = m.group(1), m.group(2)
    elif not raw_month and raw_year:
        m = re.search(r"(\d{1,2})\s*[/\-]\s*(\d{2,4})", raw_year)
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


def get_card_from_db() -> dict:
    """
    @brief 从数据库获取可用的卡片信息
    @return 卡信息字典，若无可用卡则返回None
    """
    try:
        from core.database import DBManager
        cards = DBManager.get_available_cards()
        if cards:
            card = cards[0]
            mm, yy = _normalize_exp_parts(card.get('exp_month', ''), card.get('exp_year', ''))
            zip_code = str(card.get('zip_code') or '').strip() or "10001"
            return {
                'id': card.get('id'),
                'number': card.get('card_number', ''),
                'exp_month': mm,
                'exp_year': yy,
                'cvv': card.get('cvv', ''),
                'zip_code': zip_code,
            }
    except Exception as e:
        print(f"[BindCard] 获取卡片失败: {e}")
    return None


def update_card_usage(card_id: int):
    """
    @brief 更新卡片使用次数
    @param card_id 卡片ID
    """
    try:
        from core.database import DBManager
        DBManager.increment_card_usage(card_id)
    except Exception as e:
        print(f"[BindCard] 更新卡片使用次数失败: {e}")


async def auto_bind_card(page: Page, card_info: dict = None, account_info: dict = None) -> Tuple[bool, str]:
    """
    @brief 自动绑卡订阅
    @param page Playwright页面对象
    @param card_info 卡信息字典 {'number', 'exp_month', 'exp_year', 'cvv'}
    @param account_info 账号信息(用于登录)
    @return (success, message)
    """
    # 优先从数据库获取卡片
    if card_info is None:
        card_info = get_card_from_db()
        if card_info is None:
            return False, "数据库中无可用卡片，请先在Web管理界面导入卡片"
    
    try:
        print("[BindCard] 开始自动绑卡流程...")
        
        # 等待页面加载
        await asyncio.sleep(3)

        # Step 0: 已订阅检测（参考 bit 项目：已订阅则直接返回成功）
        try:
            try:
                if await page.locator('text=/already\\s+subscribed/i').count() > 0:
                    print("[BindCard] ✅ 检测到账号已订阅(You're already subscribed)，跳过绑卡流程")
                    if account_info and account_info.get("email"):
                        try:
                            from core.database import DBManager
                            DBManager.update_account_status(account_info["email"], "subscribed")
                        except Exception:
                            pass
                    return True, "已订阅 (Already Subscribed)"
            except Exception:
                pass

            from google.backend.google_auth import check_google_one_status

            status, _ = await check_google_one_status(page, timeout=12)
            if status in ("subscribed", "subscribed_antigravity"):
                print("[BindCard] ✅ 检测到账号已订阅，跳过绑卡流程")
                if account_info and account_info.get("email"):
                    try:
                        from core.database import DBManager
                        DBManager.update_account_status(account_info["email"], status)
                    except Exception:
                        pass
                return True, f"已订阅 (Already Subscribed: {status})"
        except Exception:
            pass
        
        # Step 1: 点击 "Get student offer" 按钮
        print("[BindCard] 步骤1: 查找Get student offer按钮...")
        try:
            selectors = [
                'button:has-text("Get student offer")',
                'button:has-text("Get offer")',
                'a:has-text("Get student offer")',
            ]
            
            for selector in selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0:
                        await element.click()
                        print(f"[BindCard] ✅ 已点击 'Get student offer'")
                        break
                except:
                    continue
            
            await asyncio.sleep(8)
        except Exception as e:
            print(f"[BindCard] Get student offer 点击失败: {e}")
        
        # Step 2: 检查是否已绑卡(订阅按钮是否出现)
        print("[BindCard] 步骤2: 检查是否已绑卡...")
        await asyncio.sleep(3)
        
        try:
            iframe_locator = page.frame_locator('iframe[src*="tokenized.play.google.com"]')
            
            subscribe_selectors = [
                'button:has-text("Subscribe")',
                'button:has-text("Subscribe now")',
                '[role="button"]:has-text("Subscribe")',
                'button:has-text("订阅")',
                'button:has-text("立即订阅")',
                '[role="button"]:has-text("订阅")',
            ]
            
            for selector in subscribe_selectors:
                try:
                    element = iframe_locator.locator(selector).first
                    if await element.count() > 0:
                        print("[BindCard] ✅ 账号已绑卡，直接订阅...")
                        await element.click()
                        await asyncio.sleep(10)
                        return await _check_subscription_status(page, account_info)
                except:
                    continue
        except:
            pass
        
        # Step 3: 切换到iframe并点击Add card
        print("[BindCard] 步骤3: 切换到iframe...")
        await asyncio.sleep(10)
        
        try:
            iframe_selector = 'iframe[src*="tokenized.play.google.com"]'
            deadline = time.time() + 40
            while time.time() < deadline:
                try:
                    if await page.locator('text=/already\\s+subscribed/i').count() > 0:
                        print("[BindCard] ✅ 未发现付款iframe，但页面显示已订阅，跳过绑卡流程")
                        if account_info and account_info.get("email"):
                            try:
                                from core.database import DBManager
                                DBManager.update_account_status(account_info["email"], "subscribed")
                            except Exception:
                                pass
                        return True, "已订阅 (Already Subscribed)"
                except Exception:
                    pass
                try:
                    if await page.locator(iframe_selector).count() > 0:
                        break
                except Exception:
                    pass
                await asyncio.sleep(1)

            iframe_count = 0
            try:
                iframe_count = await page.locator(iframe_selector).count()
            except Exception:
                iframe_count = 0
            if iframe_count <= 0:
                return False, "未发现付款iframe（可能页面未加载完成/网络问题/账号已订阅）"

            iframe_locator = page.frame_locator(iframe_selector)
            try:
                await iframe_locator.locator("body").first.wait_for(state="attached", timeout=15000)
            except Exception:
                pass
            print("[BindCard] ✅ 找到付款iframe")
             
            # 点击 Add card
            await asyncio.sleep(10)
            add_card_selectors = [
                'span.PjwEQ:has-text("Add card")',
                ':text("Add card")',
            ]
            
            for selector in add_card_selectors:
                try:
                    element = iframe_locator.locator(selector).first
                    if await element.count() > 0:
                        await element.click()
                        print("[BindCard] ✅ 已点击 'Add card'")
                        break
                except:
                    continue
            
            await asyncio.sleep(10)
            
            # 检查是否有第二层iframe
            try:
                inner_iframe = iframe_locator.frame_locator('iframe[name="hnyNZeIframe"]')
                test = inner_iframe.locator('body')
                if await test.count() > 0:
                    iframe_locator = inner_iframe
                    print("[BindCard] ✅ 找到第二层iframe")
                    await asyncio.sleep(10)
            except:
                pass
            
        except Exception as e:
            return False, f"未找到付款iframe: {e}"
        
        # Step 4: 填写卡号
        print(f"[BindCard] 步骤4: 填写卡号 {card_info['number'][:4]}****")
        await asyncio.sleep(2)
        
        try:
            resolved = None
            candidates = []
            try:
                candidates.append(iframe_locator.frame_locator('iframe[name="hnyNZeIframe"]'))
            except Exception:
                pass
            candidates.append(iframe_locator)
            for cand in candidates:
                try:
                    inputs = cand.locator('input')
                    await inputs.first.wait_for(state='visible', timeout=8000)
                    if await inputs.count() >= 3:
                        resolved = cand
                        break
                except Exception:
                    continue
            if resolved is not None:
                iframe_locator = resolved

            all_inputs = iframe_locator.locator('input')
            input_count = await all_inputs.count()
            print(f"[BindCard] 找到 {input_count} 个输入框")
            
            if input_count < 3:
                return False, f"输入框数量不足: {input_count}"
            
            # 填写卡号、过期日期、CVV（先click再fill，确保输入不被清空）
            card_number_input = all_inputs.nth(0)
            await card_number_input.click()
            await asyncio.sleep(0.2)
            await card_number_input.fill(card_info['number'])
            await asyncio.sleep(0.5)
            # 验证卡号是否填写成功
            filled_value = await card_number_input.input_value()
            if not filled_value or len(filled_value.replace(' ', '').replace('-', '')) < 10:
                print("[BindCard] ⚠️ 卡号可能未正确填写，使用type方式重试...")
                await card_number_input.click()
                await asyncio.sleep(0.1)
                await card_number_input.press("Control+a")
                await asyncio.sleep(0.05)
                await card_number_input.press("Backspace")
                await asyncio.sleep(0.1)
                await card_number_input.type(card_info['number'], delay=50)
                await asyncio.sleep(0.5)
            print("[BindCard] ✅ 卡号已填写")
            
            exp_month, exp_year = _normalize_exp_parts(card_info.get('exp_month', ''), card_info.get('exp_year', ''))
            exp_input = all_inputs.nth(1)
            await exp_input.click()
            await asyncio.sleep(0.1)
            await exp_input.fill(f"{exp_month}{exp_year}")
            await asyncio.sleep(0.3)
            print("[BindCard] ✅ 过期日期已填写")
            
            cvv_input = all_inputs.nth(2)
            await cvv_input.click()
            await asyncio.sleep(0.1)
            await cvv_input.fill(card_info['cvv'])

            print("[BindCard] ✅ CVV已填写")
            await asyncio.sleep(0.3)

            # Billing zip code（可能存在，也可能不需要；兜底 10001）
            zip_code = str(card_info.get('zip_code') or card_info.get('zip') or card_info.get('postal') or '').strip() or "10001"
            zip_filled = False

            async def safe_fill_input(loc, value: str) -> bool:
                """安全填写输入框：click -> fill -> 验证 -> 必要时用type重试"""
                try:
                    await loc.click()
                    await asyncio.sleep(0.2)
                    await loc.fill(value)
                    await asyncio.sleep(0.5)
                    # 验证是否填写成功
                    filled = await loc.input_value()
                    if filled and filled.replace(' ', '').replace('-', '') == value.replace(' ', '').replace('-', ''):
                        return True
                    # 重试用type方式
                    print(f"[BindCard] ⚠️ 填写验证失败，使用type方式重试...")
                    await loc.click()
                    await asyncio.sleep(0.1)
                    await loc.press("Control+a")
                    await asyncio.sleep(0.05)
                    await loc.press("Backspace")
                    await asyncio.sleep(0.1)
                    await loc.type(value, delay=50)
                    await asyncio.sleep(0.5)
                    return True
                except Exception as e:
                    print(f"[BindCard] 填写失败: {e}")
                    return False

            def _zip_hint_ok(h: str) -> bool:
                h = (h or "").lower()
                return any(
                    k in h
                    for k in (
                        "zip",
                        "zipcode",
                        "zip code",
                        "postal",
                        "postal code",
                        "postcode",
                        "post code",
                        "pin code",
                        "pincode",
                        "邮编",
                        "邮政编码",
                    )
                )

            def _name_hint_ok(h: str) -> bool:
                h = (h or "").lower()
                return any(
                    k in h
                    for k in (
                        "name",
                        "cardholder",
                        "card holder",
                        "cc-name",
                        "持卡人",
                        "姓名",
                        "名字",
                    )
                )

            # 1) 优先在当前表单里按属性匹配（通常包含 placeholder/aria-label/autocomplete）
            for idx in range(3, input_count):
                try:
                    loc = all_inputs.nth(idx)
                    if not await loc.is_visible():
                        continue
                    label = (await loc.get_attribute('aria-label') or '')
                    placeholder = (await loc.get_attribute('placeholder') or '')
                    name = (await loc.get_attribute('name') or '')
                    autocomplete = (await loc.get_attribute('autocomplete') or '')
                    hint = f"{label} {placeholder} {name} {autocomplete}"
                    if _zip_hint_ok(hint):
                        zip_filled = await safe_fill_input(loc, zip_code)
                        if zip_filled:
                            break
                except Exception:
                    continue

            # 2) 兜底：表单里找“可见且为空”的最后一个输入框（避免把 zip 填进姓名框）
            if not zip_filled:
                for idx in range(input_count - 1, 2, -1):
                    try:
                        loc = all_inputs.nth(idx)
                        if not await loc.is_visible():
                            continue
                        label = (await loc.get_attribute('aria-label') or '')
                        placeholder = (await loc.get_attribute('placeholder') or '')
                        name = (await loc.get_attribute('name') or '')
                        autocomplete = (await loc.get_attribute('autocomplete') or '')
                        hint = f"{label} {placeholder} {name} {autocomplete}".lower()
                        if _name_hint_ok(hint):
                            continue
                        val = (await loc.input_value() or "").strip()
                        if not val:
                            zip_filled = await safe_fill_input(loc, zip_code)
                            if zip_filled:
                                break
                    except Exception:
                        continue

            # 3) 仍未命中：跨 iframe 再扫一遍（不同账号/地区表单结构可能不同）
            if not zip_filled:
                payment_iframe = page.frame_locator('iframe[src*="tokenized.play.google.com"]')
                zip_scopes = []
                try:
                    zip_scopes.append(payment_iframe.frame_locator('iframe[name="hnyNZeIframe"]'))
                except Exception:
                    pass
                zip_scopes.extend([iframe_locator, payment_iframe, page])
                for scope in zip_scopes:
                    try:
                        inputs = scope.locator('input')
                        count = await inputs.count()
                        for idx in range(count):
                            loc = inputs.nth(idx)
                            try:
                                if not await loc.is_visible():
                                    continue
                            except Exception:
                                continue
                            label = (await loc.get_attribute('aria-label') or '')
                            placeholder = (await loc.get_attribute('placeholder') or '')
                            name = (await loc.get_attribute('name') or '')
                            autocomplete = (await loc.get_attribute('autocomplete') or '')
                            hint = f"{label} {placeholder} {name} {autocomplete}"
                            if _zip_hint_ok(hint):
                                zip_filled = await safe_fill_input(loc, zip_code)
                                if zip_filled:
                                    break
                    except Exception:
                        continue
                    if zip_filled:
                        break

            if zip_filled:
                print("[BindCard] ✅ Zip已填写")
            else:
                print("[BindCard] ⚠️ 未找到Zip输入框")
            if zip_filled and input_count > 3:
                try:
                    zip_verified = False
                    for idx in range(3, input_count):
                        loc = all_inputs.nth(idx)
                        if not await loc.is_visible():
                            continue
                        val = (await loc.input_value() or "").strip()
                        if val == zip_code:
                            zip_verified = True
                            break
                    if not zip_verified:
                        print("[BindCard] ⚠️ Zip可能未写入到当前可见输入框")
                except Exception:
                    pass
            print("[BindCard] ✅ CVV已填写")
            
        except Exception as e:
            return False, f"填写卡信息失败: {e}"
        
        # Step 5: 点击 Save card
        print("[BindCard] 步骤5: 保存卡信息...")
        try:
            save_selectors = [
                'button:has-text("Save card")',
                'button:has-text("Save")',
            ]
            
            saved_clicked = False
            for selector in save_selectors:
                try:
                    element = iframe_locator.locator(selector).first
                    if await element.count() > 0 and await element.is_visible():
                        clicked = False
                        try:
                            await element.click(force=True, timeout=3000)
                            clicked = True
                        except Exception:
                            try:
                                await element.evaluate("el => el.click()")
                                clicked = True
                            except Exception:
                                clicked = False
                        if not clicked:
                            continue
                        print("[BindCard] ✅ 已点击 'Save card'")
                        saved_clicked = True
                        break
                except:
                    continue

            if not saved_clicked:
                return False, "未找到 Save card 按钮"

            # 等待表单处理完成（避免仍停留在绑卡表单导致后续订阅按钮不可用）
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    still_form = await iframe_locator.locator('button:has-text("Save card")').count() > 0
                    if not still_form:
                        break
                except Exception:
                    break
                await asyncio.sleep(1)
            
        except Exception as e:
            return False, f"保存卡失败: {e}"
        
        # Step 6: 点击订阅按钮
        print("[BindCard] 步骤6: 等待订阅页面...")
        await asyncio.sleep(5)
        
        try:
            subscribe_selectors = [
                'button:has-text("Subscribe")',
                'button:has-text("Subscribe now")',
                'button:has-text("Start subscription")',
                'button:has-text("Start plan")',
                'button:has-text("Continue")',
                'button:has-text("订阅")',
                'button:has-text("立即订阅")',
                'button:has-text("开始订阅")',
                'button:has-text("继续")',
            ]

            async def _click_best(locator) -> bool:
                try:
                    count = await locator.count()
                except Exception:
                    return False
                best = None
                best_score = None
                for idx in range(count):
                    el = locator.nth(idx)
                    try:
                        if not await el.is_visible():
                            continue
                    except Exception:
                        continue
                    try:
                        if not await el.is_enabled():
                            continue
                    except Exception:
                        pass
                    try:
                        box = await el.bounding_box()
                    except Exception:
                        box = None
                    score = None
                    if box:
                        bottom = (box.get("y", 0) or 0) + (box.get("height", 0) or 0)
                        right = (box.get("x", 0) or 0) + (box.get("width", 0) or 0)
                        area = (box.get("width", 0) or 0) * (box.get("height", 0) or 0)
                        score = bottom * 1_000_000_000 + right * 1_000_000 + area
                    else:
                        score = idx
                    try:
                        tag = await el.evaluate("el => el.tagName")
                        if (tag or "").upper() == "BUTTON":
                            score += 50_000
                    except Exception:
                        pass
                    try:
                        cls = await el.get_attribute("class") or ""
                        if "VfPpkd-LgbsSe" in cls:
                            score += 100_000
                    except Exception:
                        pass
                    if best is None or (best_score is None) or (score > best_score):
                        best = el
                        best_score = score
                if best is None:
                    return False
                try:
                    await best.scroll_into_view_if_needed()
                except Exception:
                    pass
                try:
                    await best.click(timeout=5000)
                    return True
                except Exception:
                    try:
                        await best.click(force=True, timeout=3000)
                        return True
                    except Exception:
                        try:
                            await best.evaluate("el => el.click()")
                            return True
                        except Exception:
                            return False

            clicked = False
            deadline = time.time() + 60
            while time.time() < deadline and not clicked:
                scopes = [page]
                for frame in page.frames:
                    url = (frame.url or "").lower()
                    name = (frame.name or "").lower()
                    if any(k in url for k in ["tokenized.play.google.com", "payments.google.com", "pay.google.com", "instrumentmanager", "payment"]):
                        if frame not in scopes:
                            scopes.append(frame)
                    elif any(k in name for k in ["paymentsmodaliframe", "ucc-", "hnynzeiframe"]):
                        if frame not in scopes:
                            scopes.append(frame)

                for frame in page.frames:
                    if frame not in scopes:
                        scopes.append(frame)

                role_name_patterns = [
                    re.compile(r"^\s*Subscribe\s*$", re.I),
                    re.compile(r"^\s*Subscribe now\s*$", re.I),
                    re.compile(r"^\s*Start subscription\s*$", re.I),
                    re.compile(r"^\s*Start plan\s*$", re.I),
                    re.compile(r"^\s*Continue\s*$", re.I),
                    re.compile(r"^\s*订阅\s*$", re.I),
                    re.compile(r"^\s*立即订阅\s*$", re.I),
                    re.compile(r"^\s*开始订阅\s*$", re.I),
                    re.compile(r"^\s*继续\s*$", re.I),
                ]

                for scope in scopes:
                    for pat in role_name_patterns:
                        try:
                            dialogs = scope.locator('[role="dialog"], dialog')
                            if await dialogs.count() > 0:
                                btns = dialogs.get_by_role("button", name=pat)
                                if await btns.count() > 0 and await _click_best(btns):
                                    print("[BindCard] ✅ 已点击订阅按钮")
                                    clicked = True
                                    break
                            else:
                                btns = scope.get_by_role("button", name=pat)
                                if await btns.count() > 0 and await _click_best(btns):
                                    print("[BindCard] ✅ 已点击订阅按钮")
                                    clicked = True
                                    break
                        except Exception:
                            continue
                    if clicked:
                        break

                if clicked:
                    break

                for scope in scopes:
                    for selector in subscribe_selectors:
                        try:
                            dialogs = scope.locator('[role="dialog"], dialog')
                            search_scope = dialogs if await dialogs.count() > 0 else scope
                            btns = search_scope.locator(selector)
                            if await btns.count() > 0 and await _click_best(btns):
                                print("[BindCard] ✅ 已点击订阅按钮")
                                clicked = True
                                break
                        except Exception:
                            continue
                    if clicked:
                        break

                if not clicked:
                    await asyncio.sleep(2)

            if not clicked:
                fallback_selectors = [
                    'button[type="submit"]',
                    'button.VfPpkd-LgbsSe-OWXEXe-k8QpJ',
                    'button.VfPpkd-LgbsSe',
                    '[role="button"][type="submit"]',
                ]
                for scope in scopes:
                    for selector in fallback_selectors:
                        try:
                            dialogs = scope.locator('[role="dialog"], dialog')
                            search_scope = dialogs if await dialogs.count() > 0 else scope
                            btns = search_scope.locator(selector)
                            if await btns.count() > 0 and await _click_best(btns):
                                print(f"[BindCard] ✅ 已点击提交按钮({selector})")
                                clicked = True
                                break
                        except Exception:
                            continue
                    if clicked:
                        break

            if not clicked:
                print("[BindCard] ⚠️ 未找到订阅按钮")

            if clicked:
                print("[BindCard] 等待订阅确认(Subscribed)...")
                deadline = time.time() + 90
                while time.time() < deadline:
                    ok, msg = await _check_subscription_status(page, account_info)
                    if ok:
                        return True, msg
                    await asyncio.sleep(2)
            else:
                await asyncio.sleep(10)
            
        except Exception as e:
            print(f"[BindCard] 订阅按钮点击失败: {e}")
        
        return await _check_subscription_status(page, account_info)
        
    except Exception as e:
        print(f"[BindCard] ❌ 绑卡失败: {e}")
        import traceback
        traceback.print_exc()
        return False, f"绑卡错误: {str(e)}"


async def _check_subscription_status(page: Page, account_info: dict = None) -> Tuple[bool, str]:
    """检查订阅状态"""
    try:
        iframe_locator = page.frame_locator('iframe[src*="tokenized.play.google.com"]')
        
        subscribed_selectors = [
            'text=/already\\s+subscribed/i',
            'text=/manage\\s+plan/i',
            ':text("Subscribed")',
            'text=Subscribed',
            ':text("已订阅")',
            'text=已订阅',
        ]
        
        for selector in subscribed_selectors:
            try:
                scopes = []
                try:
                    scopes.append(iframe_locator)
                except Exception:
                    pass
                scopes.append(page)
                try:
                    scopes.extend([f for f in page.frames if f not in scopes])
                except Exception:
                    pass

                for scope in scopes:
                    try:
                        element = scope.locator(selector).first
                        if await element.count() > 0:
                            print("[BindCard] ✅ 检测到 'Subscribed'，订阅成功！")

                            # 更新数据库状态
                            if account_info and account_info.get('email'):
                                try:
                                    from core.database import DBManager
                                    DBManager.update_account_status(account_info['email'], 'subscribed')
                                except Exception:
                                    pass

                            return True, "绑卡订阅成功 (Subscribed)"
                    except Exception:
                        continue
            except:
                continue
        try:
            still_form = await iframe_locator.locator('button:has-text("Save card")').count() > 0
            if still_form:
                return False, "仍在绑卡表单（可能缺少zip等），未检测到 Subscribed"
        except Exception:
            pass

        return False, "未检测到 Subscribed，绑卡订阅未完成"
        
    except Exception as e:
        return False, f"订阅状态检查异常: {e}"


def process_bind_card(browser_id: str, card_info: dict = None, log_callback: Callable = None) -> Tuple[bool, str]:
    """
    @brief 处理单个浏览器的绑卡订阅
    @param browser_id 浏览器ID
    @param card_info 卡信息
    @param log_callback 日志回调
    @return (success, message)
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)
    
    log("打开浏览器...")
    
    try:
        from core.bit_api import open_browser, close_browser, get_browser_info
        from core.database import DBManager
        from google.backend.google_auth import ensure_google_login
    except ImportError as e:
        return False, f"导入失败: {e}"
    
    # 获取账号信息
    account_info = None
    try:
        row = DBManager.get_account_by_browser_id(browser_id)
        if row:
            recovery = row.get('recovery_email') or ''
            secret = row.get('secret_key') or ''
            account_info = {
                'email': row.get('email') or '',
                'password': row.get('password') or '',
                'backup': recovery,
                'backup_email': recovery,
                'secret': secret,
                '2fa_secret': secret
            }
        else:
            browser_info = get_browser_info(browser_id)
            if browser_info:
                from core.database import build_account_info_from_remark
                account_info = build_account_info_from_remark(browser_info.get('remark', ''))
    except Exception:
        pass
    
    # 打开浏览器
    result = open_browser(browser_id)
    if not result.get('success'):
        return False, f"打开浏览器失败: {result.get('msg', '未知错误')}"
    
    ws_endpoint = result['data']['ws']
    
    async def _run():
        async with async_playwright() as playwright:
            try:
                browser = await playwright.chromium.connect_over_cdp(ws_endpoint)
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else await context.new_page()
                
                # 导航到目标页面
                target_url = "https://one.google.com/ai-student?g1_landing_page=75"
                log("导航到Google One学生页面...")
                await page.goto(target_url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(5)
                
                # 确保已登录
                if account_info:
                    log("检查登录状态...")
                    success, msg = await ensure_google_login(page, account_info)
                    if not success:
                        return False, f"登录失败: {msg}"
                    
                    # 重新导航
                    await page.goto(target_url, wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(5)
                
                # 执行绑卡
                return await auto_bind_card(page, card_info, account_info)
                
            except Exception as e:
                return False, str(e)
    
    success, msg = asyncio.run(_run())
    
    # 订阅成功后自动关闭浏览器
    if success:
        try:
            log("订阅成功，关闭浏览器...")
            close_browser(browser_id)
        except Exception as e:
            log(f"关闭浏览器失败: {e}")
    
    return success, msg
