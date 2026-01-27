"""
@file qq_email.py
@brief QQ邮箱IMAP读取模块
@details 通过IMAP协议读取QQ邮箱中的Google验证码，支持自定义域名catch-all
"""
import imaplib
import email
from email.header import decode_header
import re
import time
import random
import string
from typing import Optional, Tuple, Callable

# QQ邮箱IMAP配置
IMAP_SERVER = "imap.qq.com"
IMAP_PORT = 993

# 自定义域名配置（catch-all转发到QQ邮箱）
DEFAULT_CUSTOM_DOMAIN = "1238988.xyz"

# 默认QQ邮箱配置（用于接收转发的验证码）
DEFAULT_QQ_EMAIL = "64445547@qq.com"
DEFAULT_QQ_AUTH_CODE = "vapnuktbosfrcbaj"


def generate_random_email(domain: str = DEFAULT_CUSTOM_DOMAIN) -> str:
    """生成随机邮箱地址"""
    prefix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
    return f"{prefix}@{domain}"


def decode_email_header(header: str) -> str:
    """解码邮件头"""
    if not header:
        return ""
    decoded_parts = decode_header(header)
    result = []
    for content, charset in decoded_parts:
        if isinstance(content, bytes):
            charset = charset or 'utf-8'
            try:
                result.append(content.decode(charset))
            except:
                result.append(content.decode('utf-8', errors='ignore'))
        else:
            result.append(content)
    return ''.join(result)


def get_email_body(msg) -> str:
    """获取邮件正文"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" or content_type == "text/html":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    body += payload.decode(charset, errors='ignore')
                except:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            body = payload.decode(charset, errors='ignore')
        except:
            pass
    return body


def extract_google_verification_code(body: str) -> Optional[str]:
    """从邮件正文中提取Google验证码"""
    # Google验证码格式：6位数字
    patterns = [
        r'(?:verification code|验证码)[:\s]*(\d{6})',
        r'(?:code is|代码是)[:\s]*(\d{6})',
        r'<b>(\d{6})</b>',
        r'>(\d{6})<',
        r'\b(\d{6})\b',  # 最后尝试匹配任意6位数字
    ]
    
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def connect_qq_email(qq_email: str, auth_code: str) -> Optional[imaplib.IMAP4_SSL]:
    """
    连接QQ邮箱
    @param qq_email QQ邮箱地址 (如 123456789@qq.com)
    @param auth_code QQ邮箱授权码（不是QQ密码！）
    @return IMAP连接对象
    """
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(qq_email, auth_code)
        return mail
    except Exception as e:
        print(f"[QQEmail] 连接失败: {e}")
        return None


def wait_for_google_verification_code(
    qq_email: str,
    auth_code: str,
    target_email: str = "",
    timeout_seconds: int = 120,
    poll_interval: int = 5,
    log_callback: Optional[Callable] = None
) -> Tuple[bool, str]:
    """
    等待并读取Google验证码邮件
    
    @param qq_email QQ邮箱地址
    @param auth_code QQ邮箱授权码
    @param target_email 目标邮箱地址（用于过滤，可选）
    @param timeout_seconds 超时时间（秒）
    @param poll_interval 轮询间隔（秒）
    @param log_callback 日志回调
    @return (success, code_or_error)
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(f"[QQEmail] {msg}")
    
    start_time = time.time()
    checked_uids = set()
    
    while time.time() - start_time < timeout_seconds:
        try:
            mail = connect_qq_email(qq_email, auth_code)
            if not mail:
                log("连接QQ邮箱失败，重试...")
                time.sleep(poll_interval)
                continue
            
            # 选择收件箱
            mail.select("INBOX")
            
            # 搜索来自Google的邮件
            search_criteria = '(FROM "google.com")'
            if target_email:
                search_criteria = f'(FROM "google.com" TO "{target_email}")'
            
            status, messages = mail.search(None, search_criteria)
            if status != "OK":
                mail.logout()
                time.sleep(poll_interval)
                continue
            
            email_ids = messages[0].split()
            
            # 从最新的邮件开始检查
            for email_id in reversed(email_ids[-20:]):  # 只检查最近20封
                uid = email_id.decode() if isinstance(email_id, bytes) else str(email_id)
                
                if uid in checked_uids:
                    continue
                
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                if status != "OK":
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # 如果指定了目标邮箱，检查收件人是否匹配
                if target_email:
                    # 检查多个可能包含原始收件人的头字段
                    recipients = []
                    for header in ['To', 'Delivered-To', 'X-Original-To', 'Envelope-To', 'X-Forwarded-To']:
                        val = msg.get(header, '')
                        if val:
                            recipients.append(val.lower())
                    
                    # 也检查邮件正文中是否包含目标邮箱
                    body_text = get_email_body(msg).lower()
                    
                    target_lower = target_email.lower()
                    if not any(target_lower in r for r in recipients) and target_lower not in body_text:
                        checked_uids.add(uid)
                        continue
                
                # 检查主题
                subject = decode_email_header(msg.get("Subject", ""))
                
                # 检查是否是验证码邮件
                if any(kw in subject.lower() for kw in ['verification', 'verify', '验证', 'code']):
                    body = get_email_body(msg)
                    code = extract_google_verification_code(body)
                    
                    if code:
                        log(f"✅ 找到验证码: {code}" + (f" (目标: {target_email})" if target_email else ""))
                        
                        # 删除已读取的验证码邮件
                        try:
                            mail.store(email_id, '+FLAGS', '\\Deleted')
                            mail.expunge()
                            log("📧 验证码邮件已删除")
                        except Exception as del_e:
                            pass  # 删除失败不影响主流程
                        
                        mail.logout()
                        return True, code
                
                checked_uids.add(uid)
            
            mail.logout()
            
            elapsed = int(time.time() - start_time)
            remaining = timeout_seconds - elapsed
            log(f"等待验证码邮件... ({remaining}秒剩余)")
            
            time.sleep(poll_interval)
            
        except Exception as e:
            log(f"读取邮件出错: {e}")
            time.sleep(poll_interval)
    
    return False, "等待验证码超时"


def get_latest_google_code(
    qq_email: str,
    auth_code: str,
    max_age_minutes: int = 10
) -> Tuple[bool, str]:
    """
    获取最近的Google验证码（不等待）
    
    @param qq_email QQ邮箱地址
    @param auth_code QQ邮箱授权码
    @param max_age_minutes 邮件最大年龄（分钟）
    @return (success, code_or_error)
    """
    try:
        mail = connect_qq_email(qq_email, auth_code)
        if not mail:
            return False, "连接QQ邮箱失败"
        
        mail.select("INBOX")
        
        # 搜索来自Google的邮件
        status, messages = mail.search(None, '(FROM "google.com")')
        if status != "OK":
            mail.logout()
            return False, "搜索邮件失败"
        
        email_ids = messages[0].split()
        
        # 检查最近的邮件
        for email_id in reversed(email_ids[-10:]):
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            if status != "OK":
                continue
            
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            
            # 检查邮件时间
            date_str = msg.get("Date", "")
            # TODO: 可以添加时间检查
            
            subject = decode_email_header(msg.get("Subject", ""))
            
            if any(kw in subject.lower() for kw in ['verification', 'verify', '验证', 'code']):
                body = get_email_body(msg)
                code = extract_google_verification_code(body)
                
                if code:
                    mail.logout()
                    return True, code
        
        mail.logout()
        return False, "未找到验证码邮件"
        
    except Exception as e:
        return False, f"读取邮件出错: {e}"


# ==================== 配置管理 ====================

import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "qq_email_config.json")


def save_qq_email_config(qq_email: str, auth_code: str) -> bool:
    """保存QQ邮箱配置"""
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "qq_email": qq_email,
                "auth_code": auth_code
            }, f)
        return True
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False


def load_qq_email_config() -> Tuple[str, str]:
    """加载QQ邮箱配置"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get("qq_email", ""), config.get("auth_code", "")
    except:
        pass
    return "", ""


def test_qq_email_connection(qq_email: str, auth_code: str) -> Tuple[bool, str]:
    """测试QQ邮箱连接"""
    try:
        mail = connect_qq_email(qq_email, auth_code)
        if mail:
            mail.logout()
            return True, "连接成功"
        return False, "连接失败"
    except Exception as e:
        return False, str(e)


if __name__ == "__main__":
    # 测试代码
    import sys
    
    if len(sys.argv) >= 3:
        qq = sys.argv[1]
        code = sys.argv[2]
        
        print(f"测试连接 {qq}...")
        success, msg = test_qq_email_connection(qq, code)
        print(f"结果: {success}, {msg}")
        
        if success:
            print("\n获取最近的Google验证码...")
            success, result = get_latest_google_code(qq, code)
            print(f"结果: {success}, {result}")
    else:
        print("用法: python qq_email.py <QQ邮箱> <授权码>")
