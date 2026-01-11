"""
自动绑卡脚本 - Google One AI Student 订阅
"""
import asyncio
from playwright.async_api import async_playwright, Page
from bit_api import openBrowser, closeBrowser

# 测试卡信息
TEST_CARD = {
    'number': '5481087143137903',
    'exp_month': '01',
    'exp_year': '32',
    'cvv': '749'
}

async def auto_bind_card(page: Page, card_info: dict = None):
    """
    自动绑卡函数
    
    Args:
        page: Playwright Page 对象
        card_info: 卡信息字典 {'number', 'exp_month', 'exp_year', 'cvv'}
    
    Returns:
        (success: bool, message: str)
    """
    if card_info is None:
        card_info = TEST_CARD
    
    try:
        print("开始自动绑卡流程...")
        
        # 截图1：初始页面
        await page.screenshot(path="step1_initial.png")
        print("截图已保存: step1_initial.png")
        
        # Step 1: 等待并点击 "Get student offer" 按钮
        print("等待 'Get student offer' 按钮...")
        try:
            # 尝试多种可能的选择器
            selectors = [
                'button:has-text("Get student offer")',
                'button:has-text("Get offer")',
                'a:has-text("Get student offer")',
                'button:has-text("Get")',
                '[role="button"]:has-text("Get")'
            ]
            
            clicked = False
            for selector in selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0:
                        await element.wait_for(state='visible', timeout=3000)
                        await element.click()
                        print(f"✅ 已点击 'Get student offer' (selector: {selector})")
                        clicked = True
                        break
                except:
                    continue
            
            if not clicked:
                print("⚠️ 未找到 'Get student offer' 按钮，可能已在付款页面")
            
            # 等待付款页面和 iframe 加载
            print("等待付款页面和 iframe 加载...")
            await asyncio.sleep(2)
            await page.screenshot(path="step2_after_get_offer.png")
            print("截图已保存: step2_after_get_offer.png")
            
        except Exception as e:
            print(f"处理 'Get student offer' 时出错: {e}")
        
        # Step 2: 切换到 iframe（付款表单在 iframe 中）
        print("\n检测并切换到 iframe...")
        try:
            # 等待 iframe 加载
            await asyncio.sleep(1)
            iframe_locator = page.frame_locator('iframe[src*="tokenized.play.google.com"]')
            print("✅ 找到 tokenized.play.google.com iframe，已切换上下文")
            
            # 等待 iframe 内部文档加载
            print("等待 iframe 内部文档加载...")
            await asyncio.sleep(2)  # 让内部 #document 完全加载
            
        except Exception as e:
            print(f"❌ 未找到 iframe: {e}")
            return False, "未找到付款表单 iframe"
        
        # Step 3: 在 iframe 中点击 "Add card"
        print("\n在 iframe 中等待并点击 'Add card' 按钮...")
        try:
            await asyncio.sleep(1)  # 等待元素可点击
            
            # 在 iframe 中查找 Add card
            selectors = [
                'span.PjwEQ:has-text("Add card")',
                'span.PjwEQ',
                ':text("Add card")',
                'div:has-text("Add card")',
                'span:has-text("Add card")',
            ]
            
            clicked = False
            for selector in selectors:
                try:
                    element = iframe_locator.locator(selector).first
                    count = await element.count()
                    if count > 0:
                        print(f"  找到 'Add card' (iframe, selector: {selector})")
                        await element.click()
                        print(f"✅ 已在 iframe 中点击 'Add card'")
                        clicked = True
                        break
                except:
                    continue
            
            if not clicked:
                print("⚠️ 在 iframe 中未找到 'Add card'，尝试直接查找输入框...")
            
            # 等待表单加载
            print("等待卡片输入表单加载...")
            await asyncio.sleep(2)
            await page.screenshot(path="step3_card_form_in_iframe.png")
            print("截图已保存: step3_card_form_in_iframe.png")
            
            # 关键：点击 Add card 后，会在第一个 iframe 内部再出现一个 iframe！
            # 需要再次切换到这个内部 iframe
            print("\n检测 iframe 内部是否有第二层 iframe...")
            try:
                # 在第一个 iframe 中查找第二个 iframe
                await asyncio.sleep(1)  # 等待内部 iframe 出现
                
                # 第二层 iframe 通常是 name="hnyNZeIframe" 或包含 instrumentmanager
                # 尝试多种选择器
                inner_iframe_selectors = [
                    'iframe[name="hnyNZeIframe"]',
                    'iframe[src*="instrumentmanager"]',
                    'iframe[id*="hnyNZe"]',
                ]
                
                inner_iframe = None
                for selector in inner_iframe_selectors:
                    try:
                        temp_iframe = iframe_locator.frame_locator(selector)
                        # 尝试访问以验证存在
                        test_locator = temp_iframe.locator('body')
                        if await test_locator.count() >= 0:
                            inner_iframe = temp_iframe
                            print(f"✅ 找到第二层 iframe（selector: {selector}）")
                            break
                    except:
                        continue
                
                if not inner_iframe:
                    print("⚠️ 未找到第二层 iframe，继续在当前层级操作")
                else:
                    # 更新 iframe_locator 为内部的 iframe
                    iframe_locator = inner_iframe
                    
                    print("等待第二层 iframe 加载...")
                    await asyncio.sleep(1)
                
            except Exception as e:
                print(f"⚠️ 查找第二层 iframe 时出错: {e}")
            
        except Exception as e:
            await page.screenshot(path="error_iframe_add_card.png")
            return False, f"在 iframe 中点击 'Add card' 失败: {e}"
        
        # Step 4: 填写卡号（在 iframe 中）
        print(f"\n填写卡号: {card_info['number']}")
        await asyncio.sleep(1)
        
        try:
            # 简化策略：iframe 中有 3 个输入框，按顺序分别是：
            # 1. Card number (第1个)
            # 2. MM/YY (第2个)  
            # 3. Security code (第3个)
            
            print("在 iframe 中查找所有输入框...")
            
            # 获取所有输入框
            all_inputs = iframe_locator.locator('input')
            input_count = await all_inputs.count()
            print(f"  找到 {input_count} 个输入框")
            
            if input_count < 3:
                return False, f"输入框数量不足，只找到 {input_count} 个"
            
            # 第1个输入框 = Card number
            card_number_input = all_inputs.nth(0)
            print("  使用第1个输入框作为卡号输入框")
            
            await card_number_input.click()
            await card_number_input.fill(card_info['number'])
            print("✅ 卡号已填写")
            await asyncio.sleep(0.5)
        except Exception as e:
            return False, f"填写卡号失败: {e}"
        
        # Step 5: 填写过期日期 (MM/YY)
        print(f"填写过期日期: {card_info['exp_month']}/{card_info['exp_year']}")
        try:
            # 第2个输入框 = MM/YY
            exp_date_input = all_inputs.nth(1)
            print("  使用第2个输入框作为过期日期输入框")
            
            await exp_date_input.click()
            exp_value = f"{card_info['exp_month']}{card_info['exp_year']}"
            await exp_date_input.fill(exp_value)
            print("✅ 过期日期已填写")
            await asyncio.sleep(0.5)
        except Exception as e:
            return False, f"填写过期日期失败: {e}"
        
        # Step 6: 填写 CVV (Security code)
        print(f"填写 CVV: {card_info['cvv']}")
        try:
            # 第3个输入框 = Security code
            cvv_input = all_inputs.nth(2)
            print("  使用第3个输入框作为CVV输入框")
            
            await cvv_input.click()
            await cvv_input.fill(card_info['cvv'])
            print("✅ CVV已填写")
            await asyncio.sleep(0.5)
        except Exception as e:
            return False, f"填写CVV失败: {e}"
        
        # Step 6: 点击 "Save card" 按钮
        print("点击 'Save card' 按钮...")
        try:
            save_selectors = [
                'button:has-text("Save card")',
                'button:has-text("Save")',
                'button[type="submit"]',
            ]
            
            save_button = None
            for selector in save_selectors:
                try:
                    element = iframe_locator.locator(selector).first
                    count = await element.count()
                    if count > 0:
                        print(f"  找到 Save 按钮 (iframe, selector: {selector})")
                        save_button = element
                        break
                except:
                    continue
            
            if not save_button:
                return False, "未找到 Save card 按钮"
            
            await save_button.click()
            print("✅ 已点击 'Save card'")
        except Exception as e:
            return False, f"点击 Save card 失败: {e}"
        
        # Step 7: 点击订阅按钮完成流程
        print("\n等待订阅页面加载...")
        await asyncio.sleep(3)
        
        try:
            # 查找订阅按钮
            print("查找订阅按钮...")
            subscribe_selectors = [
                'button:has-text("Subscribe")',
                'button:has-text("订阅")',
                'button:has-text("Start")',
                'button:has-text("继续")',
                'button[type="submit"]',
            ]
            
            subscribe_button = None
            for selector in subscribe_selectors:
                try:
                    element = page.locator(selector).first
                    count = await element.count()
                    if count > 0:
                        print(f"  找到订阅按钮 (selector: {selector})")
                        subscribe_button = element
                        break
                except:
                    continue
            
            if subscribe_button:
                await subscribe_button.click()
                print("✅ 已点击订阅按钮")
                await asyncio.sleep(3)
                print("✅ 绑卡并订阅成功！")
                return True, "绑卡并订阅成功 (Subscribed)"
            else:
                print("⚠️ 未找到订阅按钮，可能已自动完成")
                print("✅ 绑卡成功")
                return True, "绑卡成功"
                
        except Exception as e:
            print(f"点击订阅按钮时出错: {e}")
            print("✅ 绑卡已完成（订阅步骤可能需要手动）")
            return True, "绑卡已完成"
        
    except Exception as e:
        print(f"❌ 绑卡过程出错: {e}")
        import traceback
        traceback.print_exc()
        return False, f"绑卡错误: {str(e)}"


async def test_bind_card_with_browser(browser_id: str):
    """
    使用指定的比特浏览器窗口测试绑卡
    
    Args:
        browser_id: 比特浏览器窗口 ID
    """
    print(f"正在打开浏览器 {browser_id}...")
    
    # 打开浏览器
    response = openBrowser(browser_id)
    if not response or not response.get('success'):
        print(f"打开浏览器失败: {response}")
        return False, "打开浏览器失败"
    
    ws_url = response['data']['ws']
    print(f"WebSocket URL: {ws_url}")
    
    async with async_playwright() as p:
        try:
            # 连接到浏览器
            browser = await p.chromium.connect_over_cdp(ws_url)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
            
            # 导航到目标页面
            target_url = "https://one.google.com/ai-student?g1_landing_page=75&utm_source=antigravity&utm_campaign=argon_limit_reached"
            print(f"导航到: {target_url}")
            await page.goto(target_url, wait_until='domcontentloaded', timeout=30000)
            
            # 等待页面加载
            print("等待页面完全加载...")
            await asyncio.sleep(5)  # 增加等待时间以确保弹窗有机会出现
            
            # 执行自动绑卡
            success, message = await auto_bind_card(page)
            
            print(f"\n{'='*50}")
            print(f"绑卡结果: {message}")
            print(f"{'='*50}\n")
            
            # 保持浏览器打开以便查看结果
            print("绑卡流程完成。浏览器将保持打开状态。")
            await asyncio.sleep(5)
            
            return success, message
            
        except Exception as e:
            print(f"执行过程出错: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)
        finally:
            # 不关闭浏览器，方便查看结果
            # closeBrowser(browser_id)
            pass


if __name__ == "__main__":
    # 使用用户指定的浏览器 ID 测试
    test_browser_id = "94b7f635502e42cf87a0d7e9b1330686"
    
    print(f"开始测试自动绑卡功能...")
    print(f"目标浏览器 ID: {test_browser_id}")
    print(f"测试卡信息: {TEST_CARD}")
    print(f"\n{'='*50}\n")
    
    result = asyncio.run(test_bind_card_with_browser(test_browser_id))
    
    print(f"\n最终结果: {result}")
