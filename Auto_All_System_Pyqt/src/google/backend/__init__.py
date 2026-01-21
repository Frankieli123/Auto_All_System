"""
@file __init__.py
@brief 谷歌业务后端模块
@details 包含谷歌账号自动化的核心业务逻辑

已迁移模块:
- account_manager: 账号状态管理
- sheerid_verifier: SheerID链接验证
- google_auth: Google登录状态检测
- google_login_service: Google登录服务
- sheerlink_service: SheerLink提取服务
- bind_card_service: 绑卡订阅服务
- all_in_one_service: 全自动处理服务
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
    ensure_google_login,
)
from .google_login_service import (
    GoogleLoginService,
    login_google_account,
    check_browser_login_status,
    quick_login_check,
)
from .sheerlink_service import (
    SheerLinkService,
    process_browser,
    extract_sheerlink_batch,
)
from .bind_card_service import (
    auto_bind_card,
    process_bind_card,
)
from .all_in_one_service import (
    process_all_in_one,
)

__all__ = [
    # 已迁移模块 - 核心类
    'SheerIDVerifier',
    'AccountManager',
    'GoogleLoginService',
    'SheerLinkService',
    # 登录状态
    'GoogleLoginStatus',
    'check_google_login_status',
    'is_logged_in',
    'navigate_and_check_login',
    'google_login',
    'check_google_one_status',
    'ensure_google_login',
    # 登录服务便捷函数
    'login_google_account',
    'check_browser_login_status',
    'quick_login_check',
    # SheerLink服务
    'process_browser',
    'extract_sheerlink_batch',
    # 绑卡服务
    'auto_bind_card',
    'process_bind_card',
    # 全自动服务
    'process_all_in_one',
]


