"""
@file temp_email.py
@brief 临时邮箱服务模块
@details 提供临时邮箱创建和验证码获取功能
"""
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, Timeout
import random
import string
import re
import time
from typing import Tuple, Optional, Callable

# 域名邮箱配置
WORKER_DOMAIN = "api.318062.xyz"
EMAIL_DOMAIN = "318062.xyz"
ADMIN_PASSWORD = "asd3865373"

_SESSION = requests.Session()
try:
    from urllib3.util.retry import Retry

    _SESSION.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=2,
                connect=2,
                read=2,
                backoff_factor=0.6,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(("GET", "POST")),
                raise_on_status=False,
            )
        ),
    )
except Exception:
    pass


def generate_random_name() -> str:
    """生成随机邮箱名称"""
    letters1 = ''.join(random.choices(string.ascii_lowercase, k=5))
    numbers = ''.join(random.choices(string.digits, k=5))
    letters2 = ''.join(random.choices(string.ascii_lowercase, k=3))
    return letters1 + numbers + letters2


def create_temp_email() -> Tuple[Optional[str], Optional[str]]:
    """
    创建临时邮箱
    @return (jwt_token, email_address) 或 (None, None) 失败
    """
    try:
        random_name = generate_random_name()
        res = _SESSION.post(
            f"https://{WORKER_DOMAIN}/admin/new_address",
            json={
                "enablePrefix": True,
                "name": random_name,
                "domain": EMAIL_DOMAIN,
            },
            headers={
                'x-admin-auth': ADMIN_PASSWORD,
                "Content-Type": "application/json"
            },
            timeout=(10, 30),
        )
        if res.status_code == 200:
            data = res.json()
            return data.get('jwt'), data.get('address')
        else:
            print(f"[TempEmail] 创建失败: {res.status_code} {res.text}")
            return None, None
    except Exception as e:
        print(f"[TempEmail] 创建异常: {e}")
        return None, None


def fetch_emails(jwt: str, limit: int = 10, request_timeout_s: int = 45) -> list:
    """
    获取邮箱列表
    @param jwt JWT令牌
    @param limit 获取数量
    @param request_timeout_s 单次请求 read timeout（秒）
    @return 邮件列表
    """
    url = f"https://{WORKER_DOMAIN}/api/mails"
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
    }

    timeouts = [
        (10, max(10, min(25, request_timeout_s))),
        (10, max(15, min(60, request_timeout_s + 20))),
    ]

    last_error = None
    for attempt, timeout in enumerate(timeouts, start=1):
        try:
            res = _SESSION.get(
                url,
                params={"limit": limit, "offset": 0},
                headers=headers,
                timeout=timeout,
            )
            if res.status_code == 200:
                data = res.json()
                return data.get("results", []) or []
            last_error = f"HTTP {res.status_code}: {res.text[:200]}"
        except Timeout as e:
            last_error = f"Timeout({timeout}): {e}"
        except RequestException as e:
            last_error = str(e)

        if attempt < len(timeouts):
            time.sleep(0.6 * attempt)

    if last_error:
        print(f"[TempEmail] 获取邮件失败: {last_error}")
    return []


def extract_google_verification_code(raw_content: str) -> Optional[str]:
    """
    从邮件原始内容中提取 Google 验证码
    @param raw_content 邮件原始内容
    @return 6位验证码 或 None
    """
    if not raw_content:
        return None
    
    # Google 验证码通常是6位数字
    patterns = [
        r'Use this code[^:]*:\s*(\d{6})',  # Google 格式
        r'finish setting up[^:]*:\s*(\d{6})',
        r'verification code[:\s]+(\d{6})',
        r'验证码[：:\s]+(\d{6})',
        r'code[:\s]+(\d{6})',
        r'code is[:\s]+(\d{6})',
        r'>(\d{6})<',
        r'\s(\d{6})\s',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, raw_content, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if match:
            return match.group(1)
    
    # 最后尝试找任何独立的6位数字
    all_codes = re.findall(r'\b(\d{6})\b', raw_content)
    if all_codes:
        return all_codes[0]
    
    return None


def wait_for_verification_code(
    jwt: str,
    timeout: int = 120,
    poll_interval: int = 5,
    log_callback: Optional[Callable] = None
) -> Optional[str]:
    """
    等待并获取验证码
    @param jwt JWT令牌
    @param timeout 超时时间（秒）
    @param poll_interval 轮询间隔（秒）
    @param log_callback 日志回调
    @return 验证码 或 None
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        print(msg)
    
    start_time = time.time()
    checked_ids = set()
    
    log(f"[TempEmail] 开始等待验证码（超时: {timeout}秒）...")
    
    while time.time() - start_time < timeout:
        remaining = int(timeout - (time.time() - start_time))
        request_timeout_s = max(10, min(45, remaining))
        emails = fetch_emails(jwt, limit=10, request_timeout_s=request_timeout_s)
        
        if emails:
            log(f"[TempEmail] 收到 {len(emails)} 封邮件")
        
        for email in emails:
            email_id = (
                email.get('id')
                or email.get('_id')
                or email.get('messageId')
                or email.get('msgId')
            )

            sender = email.get('from', '') or ''
            subject = email.get('subject', '') or ''
            raw_content = email.get('raw', '') or email.get('text', '') or email.get('html', '')

            # 某些实现不返回稳定 id：使用轻量指纹去重，避免重复打印/重复解析
            if email_id:
                fingerprint = f"id:{email_id}"
            else:
                fingerprint = f"fp:{sender[:64]}|{subject[:80]}|{raw_content[:120]}"
            if fingerprint in checked_ids:
                continue
            checked_ids.add(fingerprint)
            
            log(f"[TempEmail] 检查邮件: from={sender[:50]}, subject={subject[:50]}")
            
            # 尝试提取验证码（不限制发件人）
            code = extract_google_verification_code(raw_content)
            if code:
                log(f"[TempEmail] ✅ 获取到验证码: {code}")
                return code
        
        elapsed = int(time.time() - start_time)
        log(f"[TempEmail] 等待中... ({elapsed}s/{timeout}s)")
        time.sleep(poll_interval)
    
    log("[TempEmail] ❌ 等待验证码超时")
    return None
