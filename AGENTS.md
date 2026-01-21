# AGENTS.md - BitBrowser Automation Tool

## 项目概述

比特浏览器自动化管理工具，支持批量创建窗口、自动分配代理、SheerID 验证链接提取、2FA 验证码管理和自动绑卡等功能。

## 技术栈

- **语言**: Python 3.12
- **GUI 框架**: PyQt6
- **浏览器自动化**: Playwright
- **数据库**: SQLite3
- **Web 服务**: Flask (web_admin)
- **其他依赖**: requests, pyotp, deep_translator

## 项目结构

```
├── create_window_gui.py    # 主 GUI 入口
├── create_window.py        # 窗口创建核心逻辑
├── bit_api.py              # 比特浏览器本地 API 封装
├── bit_playwright.py       # Playwright 浏览器操作
├── run_playwright_google.py # Google 登录 + SheerID 提取自动化
├── sheerid_gui.py          # SheerID 验证 GUI
├── sheerid_verifier.py     # SheerID 验证核心逻辑
├── auto_bind_card.py       # 自动绑卡功能
├── auto_all_in_one_gui.py  # 一键全自动处理 GUI
├── account_manager.py      # 账号管理器
├── database.py             # SQLite 数据库操作 (DBManager)
├── migrate_txt_to_db.py    # 文本文件迁移到数据库
└── web_admin/              # Web 管理界面
    ├── server.py           # Flask 服务器 (端口 8080)
    ├── static/             # 静态资源
    └── templates/          # HTML 模板
```

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 运行主程序
python create_window_gui.py

# 单独测试
python test.py
```

## 代码规范

- 中文注释和日志输出
- 使用 `----` 作为默认字段分隔符（账号文件）
- 线程安全：数据库操作使用 `threading.Lock`
- 日志回调模式：核心函数接受 `log_callback` 参数
- PyQt6 信号槽机制处理 UI 更新

## 数据流

1. **账号数据源**: `accounts.txt` → `database.py` (DBManager) → `accounts.db`
2. **状态同步**: 数据库为单一数据源，自动同步到文本文件
3. **状态类型**: `pending`, `link_ready`, `verified`, `subscribed`, `ineligible`, `error`

## 配置文件

| 文件 | 用途 |
|------|------|
| `accounts.txt` | 账号信息（邮箱、密码、辅助邮箱、2FA密钥）|
| `proxies.txt` | 代理 IP 列表 |
| `cards.txt` | 虚拟卡信息 |

## 核心类/模块

- `BrowserWindowCreatorGUI`: 主窗口类 (create_window_gui.py)
- `WorkerThread`: 通用后台工作线程
- `DBManager`: 数据库管理静态类 (database.py)
- `AccountManager`: 账号管理器 (account_manager.py)
- `SheerIDVerifier`: SheerID 验证器 (sheerid_verifier.py)

## 比特浏览器 API

本地服务地址: `http://127.0.0.1:54345`

主要接口:
- `/browser/update` - 创建/更新窗口
- `/browser/open` - 打开窗口
- `/browser/close` - 关闭窗口
- `/browser/delete` - 删除窗口
- `/browser/list` - 获取窗口列表

## 注意事项

- 比特浏览器需要先启动本地服务
- Web Admin 自动在 8080 端口启动
- 使用 PyInstaller 打包时需包含 `beta-1.svg` 图标
- 密码支持特殊字符，但分隔符不能出现在密码中
