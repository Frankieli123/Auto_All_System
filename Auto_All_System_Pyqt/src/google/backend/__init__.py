"""
@file __init__.py
@brief 谷歌业务后端模块
@details 包含谷歌账号自动化的核心业务逻辑

已迁移模块:
- account_manager: 账号状态管理
- sheerid_verifier: SheerID链接验证
- google_auth: Google登录状态检测和自动登录
"""

from .sheerid_verifier import SheerIDVerifier
from .account_manager import AccountManager
from .google_auth import (
    GoogleLoginStatus,
    check_google_login_status,
    is_logged_in,
    navigate_and_check_login,
    google_login,
    check_google_one_status,
)

# 待迁移的模块 - 目前从旧位置导入
try:
    import sys
    import os
    _src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _legacy_dir = os.path.join(_src_dir, '_legacy')
    if _legacy_dir not in sys.path:
        sys.path.insert(0, _legacy_dir)
    
    from run_playwright_google import process_browser
    from auto_bind_card import auto_bind_card, check_and_login
except ImportError as e:
    print(f"[google.backend] 部分模块导入失败: {e}")
    process_browser = None
    auto_bind_card = check_and_login = None

__all__ = [
    # 已迁移模块
    'SheerIDVerifier',
    'AccountManager',
    'GoogleLoginStatus',
    'check_google_login_status',
    'is_logged_in',
    'navigate_and_check_login',
    'google_login',
    'check_google_one_status',
    # 待迁移模块
    'process_browser', 
    'auto_bind_card',
    'check_and_login',
]

