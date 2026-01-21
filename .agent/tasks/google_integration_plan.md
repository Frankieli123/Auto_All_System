# Google功能集成计划

## 当前状态
✅ 已完成：
- 一键获取 G-SheerLink (使用WorkerThread多线程)
- 登录流程优化
- 资格判断逻辑
- 全局并发数对接

## 待集成功能

### 1. 批量验证 SheerID Link ⏳
**Legacy代码**: `_legacy/sheerid_verifier.py`

**功能**: 批量验证SheerID链接状态并更新数据库

**实现步骤**:
1. 迁移验证逻辑到 `google/backend/sheerid_verifier.py` (已存在)
2. 在 `WorkerThread` 添加 `run_verify_sheerid()` 方法
3. 在 `main_window.py` 添加 `_action_verify_sheerid()` 方法
4. 对接数据库状态更新

### 2. 一键绑卡订阅 ⏳  
**Legacy代码**: `_legacy/auto_bind_card.py`

**功能**: 自动登录 → 验证资格 → 绑定测试卡 → 订阅

**核心函数**:
- `auto_bind_card(page, card_info, account_info)`: 自动绑卡
- `check_and_login(page, account_info)`: 检测并登录

**实现步骤**:
1. 迁移绑卡逻辑到 `google/backend/auto_bind_card.py`
2. 在 `WorkerThread` 添加 `run_bind_card()` 方法
3. 在 `main_window.py` 添加 `_action_bind_card()` 方法
4. 使用 `ensure_google_login` 替代 `check_and_login`
5. 对接数据库更新订阅状态

### 3. 一键全自动处理 ⏳
**Legacy代码**: `_legacy/auto_all_in_one_gui.py`

**功能**: 全自动流程（提取链接 → 验证SheerID → 绑卡订阅）

**实现步骤**:
1. 创建 `google/backend/auto_all_in_one.py`
2. 封装完整流程:
   - 登录检测
   - SheerLink提取
   - SheerID验证
   - 绑卡订阅
3. 在 `WorkerThread` 添加 `run_all_in_one()` 方法
4. 在 `main_window.py` 添加 `_action_all_in_one()` 方法

## 数据库对接

### 账号状态流转
```
unverified (未验证)
  ↓ [提取SheerLink]
link_ready (有资格待验证)
  ↓ [验证SheerID]
verified (已验证未绑卡)
  ↓ [绑卡订阅]
subscribed (已订阅)
```

### 无资格分类
```
ineligible (无资格)
error (错误/超时)
```

## WorkerThread 扩展

需要添加的任务类型:
- `verify_sheerid`: 批量验证SheerID
- `bind_card`: 批量绑卡订阅
- `all_in_one`: 全自动处理

## UI集成

### main_window.py 按钮
```python
# Google专区
self.btn_get_sheerlink = QPushButton("一键获取 G-SheerLink")  ✅ 已完成
self.btn_verify_sheerid = QPushButton("批量验证 SheerID Link")  ⏳ 待实现
self.btn_bind_card = QPushButton("🔗 一键绑卡订阅")  ⏳ 待实现
self.btn_all_in_one = QPushButton("🔧 一键全自动处理")  ⏳ 待实现
```

## 实现优先级
1. **批量验证 SheerID** (高)
2. **一键绑卡订阅** (高)
3. **一键全自动处理** (中)
