/**
 * Auto All System - Web Admin JavaScript
 * @description 现代化管理界面的前端逻辑
 */

// ==================== 全局状态 ====================
const state = {
    currentPage: 'dashboard',
    accounts: [],
    proxies: [],
    cards: [],
    logs: [],
    stats: {},
    selectedAccounts: new Set(),
    selectedProxies: new Set(),
    selectedCards: new Set(),
    showSecrets: true,  // 默认显示密码/密钥
};

// ==================== API 封装 ====================
const api = {
    baseUrl: '',
    
    async request(endpoint, options = {}) {
        try {
            const response = await fetch(this.baseUrl + endpoint, {
                headers: {
                    'Content-Type': 'application/json',
                },
                ...options,
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }
            
            return data;
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            throw error;
        }
    },
    
    get(endpoint) {
        const joiner = endpoint.includes('?') ? '&' : '?';
        return this.request(`${endpoint}${joiner}_ts=${Date.now()}`, { cache: 'no-store' });
    },
    
    post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },
};

// ==================== 页面初始化 ====================
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    loadDashboard();
    
    // 定时刷新
    setInterval(() => {
        if (state.currentPage === 'dashboard') {
            loadStats();
        }
    }, 30000);
});

// ==================== 导航 ====================
function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item[data-page]');
    
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.dataset.page;
            navigateTo(page);
        });
    });
}

function navigateTo(page) {
    // 更新导航状态
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
    });
    
    // 更新页面显示
    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === `page-${page}`);
    });
    
    // 更新标题
    const titles = {
        'dashboard': '仪表盘',
        'accounts': '账号管理',
        'proxies': '代理管理',
        'cards': '卡片管理',
        'logs': '操作日志',
        'settings': '系统设置',
    };
    document.getElementById('page-title').textContent = titles[page] || page;
    
    state.currentPage = page;
    
    // 加载页面数据
    switch (page) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'accounts':
            loadAccounts();
            break;
        case 'proxies':
            loadProxies();
            break;
        case 'cards':
            loadCards();
            break;
        case 'logs':
            loadLogs();
            break;
        case 'settings':
            loadSettings();
            break;
    }
}

// ==================== Dashboard ====================
async function loadDashboard() {
    await loadStats();
}

async function loadStats() {
    try {
        const stats = await api.get('/api/system/stats');
        state.stats = stats;
        
        // 更新统计卡片
        document.getElementById('stat-accounts').textContent = stats.total_accounts || 0;
        document.getElementById('stat-verified').textContent = 
            (stats.accounts?.verified || 0) + (stats.accounts?.subscribed || 0);
        document.getElementById('stat-proxies').textContent = stats.available_proxies || 0;
        document.getElementById('stat-cards').textContent = stats.available_cards || 0;
        
        // 更新侧边栏徽章
        document.getElementById('accounts-count').textContent = stats.total_accounts || 0;
        document.getElementById('proxies-count').textContent = stats.total_proxies || 0;
        document.getElementById('cards-count').textContent = stats.total_cards || 0;
        
        // 更新状态分布条
        updateStatusBars(stats.accounts || {});
        
    } catch (error) {
        showToast('加载统计数据失败', 'error');
    }
}

function updateStatusBars(accountStats) {
    const container = document.getElementById('status-bars');
    const total = Object.values(accountStats).reduce((a, b) => a + b, 0) || 1;
    
    const statusConfig = {
        'pending_check': { label: '待检查', color: '#fbbf24' },
        'link_ready': { label: '链接就绪', color: '#60a5fa' },
        'verified': { label: '已验证', color: '#34d399' },
        'subscribed': { label: '已订阅', color: '#a78bfa' },
        'ineligible': { label: '无资格', color: '#f87171' },
        'error': { label: '错误', color: '#ef4444' },
    };
    
    container.innerHTML = Object.entries(statusConfig).map(([key, config]) => {
        const count = accountStats[key] || 0;
        const percent = Math.round((count / total) * 100);
        
        return `
            <div class="status-bar-item">
                <span class="status-bar-label">${config.label}</span>
                <div class="status-bar-track">
                    <div class="status-bar-fill" style="width: ${percent}%; background: ${config.color};"></div>
                </div>
                <span class="status-bar-value">${count}</span>
            </div>
        `;
    }).join('');
}

// ==================== Accounts ====================
async function loadAccounts() {
    try {
        const status = document.getElementById('filter-status')?.value || '';
        const url = status ? `/api/accounts?status=${status}` : '/api/accounts';
        const result = await api.get(url);
        state.accounts = result.data || [];
        renderAccountsTable();
    } catch (error) {
        showToast('加载账号失败', 'error');
    }
}

function renderAccountsTable() {
    const tbody = document.getElementById('accounts-table-body');
    const searchTerm = document.getElementById('search-accounts')?.value?.toLowerCase() || '';
    
    const filtered = state.accounts.filter(acc => 
        acc.email?.toLowerCase().includes(searchTerm)
    );
    
    if (filtered.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="text-align: center; padding: 40px; color: var(--text-muted);">
                    暂无数据
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = filtered.map(acc => {
        const pwdDisplay = state.showSecrets ? (acc.password || '-') : (acc.password ? '••••••••' : '-');
        const secretDisplay = state.showSecrets ? (acc.secret_key || '-') : (acc.secret_key ? '••••••' : '-');
        
        return `
        <tr>
            <td>
                <input type="checkbox" class="account-checkbox" data-email="${acc.email}"
                       ${state.selectedAccounts.has(acc.email) ? 'checked' : ''}
                       onchange="toggleAccountSelection('${acc.email}')">
            </td>
            <td>
                <span class="email-cell" onclick="copyToClipboard('${acc.email}')" 
                      style="cursor: pointer;" title="点击复制">
                    ${acc.email || '-'}
                </span>
            </td>
            <td class="password-cell">
                <span onclick="copyToClipboard('${acc.password || ''}')" 
                      style="cursor: pointer;" title="点击复制">
                    ${pwdDisplay}
                </span>
            </td>
            <td>${acc.recovery_email || '-'}</td>
            <td class="password-cell">
                <span onclick="copyToClipboard('${acc.secret_key || ''}')" 
                      style="cursor: pointer;" title="点击复制">
                    ${secretDisplay}
                </span>
            </td>
            <td>
                <span class="status-tag ${acc.status || 'pending_check'}">
                    ${getStatusLabel(acc.status)}
                </span>
            </td>
            <td>${formatDate(acc.updated_at)}</td>
            <td>
                <button class="btn btn-ghost btn-icon-only" onclick="editAccount('${acc.email}')" title="编辑">
                    ✏️
                </button>
                <button class="btn btn-ghost btn-icon-only" onclick="deleteAccount('${acc.email}')" title="删除">
                    🗑️
                </button>
            </td>
        </tr>
    `;
    }).join('');
}

function filterAccounts() {
    loadAccounts();
}

function searchAccounts() {
    renderAccountsTable();
}

function toggleAccountSelection(email) {
    if (state.selectedAccounts.has(email)) {
        state.selectedAccounts.delete(email);
    } else {
        state.selectedAccounts.add(email);
    }
}

function toggleSelectAll(type) {
    const checkbox = document.getElementById(`select-all-${type}`);
    const items = type === 'accounts' ? state.accounts : 
                  type === 'proxies' ? state.proxies : state.cards;
    const selected = type === 'accounts' ? state.selectedAccounts :
                     type === 'proxies' ? state.selectedProxies : state.selectedCards;
    
    selected.clear();
    
    if (checkbox.checked) {
        items.forEach(item => {
            const key = type === 'accounts' ? item.email : item.id;
            selected.add(key);
        });
    }
    
    // 重新渲染表格
    if (type === 'accounts') renderAccountsTable();
    else if (type === 'proxies') renderProxiesTable();
    else if (type === 'cards') renderCardsTable();
}

async function importAccounts() {
    const text = document.getElementById('import-accounts-text').value;
    const separator = document.getElementById('import-accounts-separator').value;
    const status = document.getElementById('import-accounts-status').value;
    
    if (!text.trim()) {
        showToast('请输入账号数据', 'warning');
        return;
    }
    
    try {
        const result = await api.post('/api/accounts/import', {
            text, separator, status
        });
        
        showToast(`成功导入 ${result.imported} 个账号`, 'success');
        closeModal();
        loadAccounts();
        loadStats();
        
        // 清空输入
        document.getElementById('import-accounts-text').value = '';
        
    } catch (error) {
        showToast(`导入失败: ${error.message}`, 'error');
    }
}

async function deleteAccount(email) {
    if (!confirm(`确定删除账号 ${email}？`)) return;
    
    try {
        await api.post('/api/accounts/delete', { emails: [email] });
        showToast('删除成功', 'success');
        loadAccounts();
        loadStats();
    } catch (error) {
        showToast(`删除失败: ${error.message}`, 'error');
    }
}

async function deleteSelectedAccounts() {
    if (state.selectedAccounts.size === 0) {
        showToast('请先选择账号', 'warning');
        return;
    }
    
    if (!confirm(`确定删除选中的 ${state.selectedAccounts.size} 个账号？`)) return;
    
    try {
        await api.post('/api/accounts/delete', { 
            emails: Array.from(state.selectedAccounts) 
        });
        showToast('删除成功', 'success');
        state.selectedAccounts.clear();
        loadAccounts();
        loadStats();
    } catch (error) {
        showToast(`删除失败: ${error.message}`, 'error');
    }
}

function editAccount(email) {
    const account = state.accounts.find(a => a.email === email);
    if (!account) {
        showToast('未找到账号', 'error');
        return;
    }
    
    document.getElementById('edit-account-email-original').value = email;
    document.getElementById('edit-account-email').value = email;
    document.getElementById('edit-account-password').value = account.password || '';
    document.getElementById('edit-account-recovery').value = account.recovery_email || '';
    document.getElementById('edit-account-secret').value = account.secret_key || '';
    document.getElementById('edit-account-status').value = account.status || 'pending_check';
    
    showModal('edit-account');
}

async function saveEditAccount() {
    const email = document.getElementById('edit-account-email-original').value;
    const password = document.getElementById('edit-account-password').value;
    const recovery_email = document.getElementById('edit-account-recovery').value;
    const secret_key = document.getElementById('edit-account-secret').value;
    const status = document.getElementById('edit-account-status').value;
    
    if (!email) {
        showToast('邮箱不能为空', 'error');
        return;
    }
    
    try {
        await api.post('/api/accounts/update', {
            email: email,
            updates: {
                password: password,
                recovery_email: recovery_email,
                secret_key: secret_key,
                status: status
            }
        });
        showToast('保存成功', 'success');
        closeModal();
        await loadAccounts();
        await loadStats();
    } catch (error) {
        showToast(`保存失败: ${error.message}`, 'error');
    }
}

async function exportAccounts() {
    // 获取筛选条件
    const statusFilter = document.getElementById('export-accounts-status')?.value || '';
    const separator = document.getElementById('export-accounts-separator')?.value || '----';
    
    // 获取要导出的字段
    const fields = ['email']; // 邮箱始终导出
    if (document.getElementById('export-field-password')?.checked) fields.push('password');
    if (document.getElementById('export-field-recovery')?.checked) fields.push('recovery_email');
    if (document.getElementById('export-field-secret')?.checked) fields.push('secret_key');
    if (document.getElementById('export-field-link')?.checked) fields.push('verification_link');
    if (document.getElementById('export-field-status')?.checked) fields.push('status');
    
    try {
        const result = await api.post('/api/accounts/export', {
            fields,
            separator,
            status: statusFilter
        });
        
        // 创建下载
        const blob = new Blob([result.data], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const statusSuffix = statusFilter ? `_${statusFilter}` : '';
        a.download = `accounts_export${statusSuffix}_${new Date().toISOString().slice(0,10)}.txt`;
        a.click();
        URL.revokeObjectURL(url);
        
        closeModal();
        showToast(`导出 ${result.count} 个账号`, 'success');
    } catch (error) {
        showToast(`导出失败: ${error.message}`, 'error');
    }
}

// ==================== Proxies ====================
async function loadProxies() {
    try {
        const result = await api.get('/api/proxies');
        state.proxies = result.data || [];
        renderProxiesTable();
    } catch (error) {
        showToast('加载代理失败', 'error');
    }
}

function renderProxiesTable() {
    const tbody = document.getElementById('proxies-table-body');
    const searchTerm = document.getElementById('search-proxies')?.value?.toLowerCase() || '';
    
    const filtered = state.proxies.filter(p => 
        p.host?.toLowerCase().includes(searchTerm)
    );
    
    if (filtered.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="text-align: center; padding: 40px; color: var(--text-muted);">
                    暂无数据
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = filtered.map(p => `
        <tr>
            <td>
                <input type="checkbox" class="proxy-checkbox" data-id="${p.id}"
                       ${state.selectedProxies.has(p.id) ? 'checked' : ''}
                       onchange="toggleProxySelection(${p.id})">
            </td>
            <td><span class="status-tag">${p.proxy_type || 'socks5'}</span></td>
            <td>${p.host}</td>
            <td>${p.port}</td>
            <td>${p.username || '-'}</td>
            <td>
                <span class="status-tag ${p.is_used ? 'used' : 'available'}">
                    ${p.is_used ? '已使用' : '可用'}
                </span>
            </td>
            <td>${p.used_by || '-'}</td>
            <td>
                <button class="btn btn-ghost btn-icon-only" onclick="deleteProxy(${p.id})" title="删除">
                    🗑️
                </button>
            </td>
        </tr>
    `).join('');
}

function searchProxies() {
    renderProxiesTable();
}

function toggleProxySelection(id) {
    if (state.selectedProxies.has(id)) {
        state.selectedProxies.delete(id);
    } else {
        state.selectedProxies.add(id);
    }
}

async function importProxies() {
    const text = document.getElementById('import-proxies-text').value;
    const type = document.getElementById('import-proxies-type').value;
    
    if (!text.trim()) {
        showToast('请输入代理数据', 'warning');
        return;
    }
    
    try {
        const result = await api.post('/api/proxies/import', { text, type });
        showToast(`成功导入 ${result.imported} 个代理`, 'success');
        closeModal();
        loadProxies();
        loadStats();
        document.getElementById('import-proxies-text').value = '';
    } catch (error) {
        showToast(`导入失败: ${error.message}`, 'error');
    }
}

async function deleteProxy(id) {
    if (!confirm('确定删除该代理？')) return;
    
    try {
        await api.post('/api/proxies/delete', { ids: [id] });
        showToast('删除成功', 'success');
        loadProxies();
        loadStats();
    } catch (error) {
        showToast(`删除失败: ${error.message}`, 'error');
    }
}

async function clearProxies() {
    if (!confirm('确定清空所有代理？此操作不可恢复！')) return;
    
    try {
        await api.post('/api/proxies/clear', {});
        showToast('已清空所有代理', 'success');
        loadProxies();
        loadStats();
    } catch (error) {
        showToast(`清空失败: ${error.message}`, 'error');
    }
}

// ==================== Cards ====================
async function loadCards() {
    try {
        const result = await api.get('/api/cards');
        state.cards = result.data || [];
        renderCardsTable();
    } catch (error) {
        showToast('加载卡片失败', 'error');
    }
}

function renderCardsTable() {
    const tbody = document.getElementById('cards-table-body');
    const searchTerm = document.getElementById('search-cards')?.value?.toLowerCase() || '';
    
    const filtered = state.cards.filter(c => 
        c.card_number?.toLowerCase().includes(searchTerm)
    );
    
    if (filtered.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="13" style="text-align: center; padding: 40px; color: var(--text-muted);">
                    暂无数据
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = filtered.map(c => {
        const cardDisplay = state.showSecrets ? 
            c.card_number : 
            (c.card_number ? c.card_number.slice(0, 4) + ' •••• •••• ' + c.card_number.slice(-4) : '-');
        const cvvDisplay = state.showSecrets ? (c.cvv || '-') : '•••';
        const isExhausted = c.usage_count >= c.max_usage;
        
        return `
            <tr>
                <td>
                    <input type="checkbox" class="card-checkbox" data-id="${c.id}"
                           ${state.selectedCards.has(c.id) ? 'checked' : ''}
                           onchange="toggleCardSelection(${c.id})">
                </td>
                <td>
                    <span onclick="copyToClipboard('${c.card_number}')" 
                          style="cursor: pointer; font-family: monospace;" title="点击复制">
                        ${cardDisplay}
                    </span>
                </td>
                <td>${c.exp_month}/${c.exp_year}</td>
                <td class="password-cell">
                    <span onclick="copyToClipboard('${c.cvv || ''}')" 
                          style="cursor: pointer;" title="点击复制">
                        ${cvvDisplay}
                    </span>
                </td>
                <td>${c.holder_name || '-'}</td>
                <td>${c.zip_code || '-'}</td>
                <td>${c.country || '-'}</td>
                <td>${c.state || '-'}</td>
                <td>${c.city || '-'}</td>
                <td title="${c.address || ''}">${c.address || '-'}</td>
                <td>${c.usage_count}/${c.max_usage}</td>
                <td>
                    <span class="status-tag ${c.is_active ? (isExhausted ? 'inactive' : 'active') : 'inactive'}">
                        ${c.is_active ? (isExhausted ? '已用尽' : '可用') : '已禁用'}
                    </span>
                </td>
                <td>
                    <button class="btn btn-ghost btn-icon-only" onclick="openEditCard(${c.id})" title="编辑">
                        ✏️
                    </button>
                    <button class="btn btn-ghost btn-icon-only" onclick="toggleCard(${c.id}, ${!c.is_active})" 
                            title="${c.is_active ? '禁用' : '启用'}">
                        ${c.is_active ? '🔒' : '🔓'}
                    </button>
                    <button class="btn btn-ghost btn-icon-only" onclick="deleteCard(${c.id})" title="删除">
                        🗑️
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function searchCards() {
    renderCardsTable();
}

function toggleCardSelection(id) {
    if (state.selectedCards.has(id)) {
        state.selectedCards.delete(id);
    } else {
        state.selectedCards.add(id);
    }
}

async function importCards() {
    const text = document.getElementById('import-cards-text').value;
    const maxUsage = parseInt(document.getElementById('import-cards-max-usage').value) || 1;
    
    if (!text.trim()) {
        showToast('请输入卡片数据', 'warning');
        return;
    }
    
    try {
        const result = await api.post('/api/cards/import', { text, max_usage: maxUsage });
        showToast(`成功导入 ${result.imported} 张卡片`, 'success');
        closeModal();
        await loadCards();
        await loadStats();
        document.getElementById('import-cards-text').value = '';
    } catch (error) {
        showToast(`导入失败: ${error.message}`, 'error');
    }
}

async function toggleCard(id, active) {
    try {
        await api.post('/api/cards/toggle', { id, active });
        showToast(active ? '卡片已启用' : '卡片已禁用', 'success');
        await loadCards();
    } catch (error) {
        showToast(`操作失败: ${error.message}`, 'error');
    }
}

async function deleteCard(id) {
    if (!confirm('确定删除该卡片？')) return;
    
    try {
        await api.post('/api/cards/delete', { ids: [id] });
        showToast('删除成功', 'success');
        await loadCards();
        await loadStats();
    } catch (error) {
        showToast(`删除失败: ${error.message}`, 'error');
    }
}

async function clearCards() {
    if (!confirm('确定清空所有卡片？此操作不可恢复！')) return;
    
    try {
        await api.post('/api/cards/clear', {});
        showToast('已清空所有卡片', 'success');
        await loadCards();
        await loadStats();
    } catch (error) {
        showToast(`清空失败: ${error.message}`, 'error');
    }
}

function openEditCard(id) {
    const card = state.cards.find(c => c.id === id);
    if (!card) return;

    document.getElementById('edit-card-id').value = card.id;
    document.getElementById('edit-card-number').value = card.card_number || '';
    document.getElementById('edit-card-month').value = parseInt(card.exp_month, 10) || '';
    document.getElementById('edit-card-year').value = parseInt(card.exp_year, 10) || '';
    document.getElementById('edit-card-cvv').value = card.cvv || '';
    document.getElementById('edit-card-holder').value = card.holder_name || '';
    document.getElementById('edit-card-zip').value = card.zip_code || '';
    document.getElementById('edit-card-country').value = card.country || '';
    document.getElementById('edit-card-state').value = card.state || '';
    document.getElementById('edit-card-city').value = card.city || '';
    document.getElementById('edit-card-address').value = card.address || '';
    document.getElementById('edit-card-max-usage').value = parseInt(card.max_usage, 10) || 1;
    document.getElementById('edit-card-active').value = (card.is_active ? 'true' : 'false');

    showModal('edit-card');
}

async function saveEditCard() {
    const payload = {
        id: parseInt(document.getElementById('edit-card-id').value, 10),
        exp_month: parseInt(document.getElementById('edit-card-month').value, 10),
        exp_year: parseInt(document.getElementById('edit-card-year').value, 10),
        cvv: document.getElementById('edit-card-cvv').value,
        holder_name: document.getElementById('edit-card-holder').value,
        zip_code: document.getElementById('edit-card-zip').value,
        country: document.getElementById('edit-card-country').value,
        state: document.getElementById('edit-card-state').value,
        city: document.getElementById('edit-card-city').value,
        address: document.getElementById('edit-card-address').value,
        max_usage: parseInt(document.getElementById('edit-card-max-usage').value, 10) || 1,
        is_active: document.getElementById('edit-card-active').value === 'true',
    };

    if (!payload.id) {
        showToast('卡片ID无效', 'error');
        return;
    }

    try {
        await api.post('/api/cards/update', payload);
        showToast('保存成功', 'success');
        closeModal();
        await loadCards();
        await loadStats();
    } catch (error) {
        showToast(`保存失败: ${error.message}`, 'error');
    }
}

// ==================== Logs ====================
async function loadLogs() {
    try {
        const result = await api.get('/api/logs?limit=100');
        state.logs = result.data || [];
        renderLogs();
    } catch (error) {
        showToast('加载日志失败', 'error');
    }
}

function renderLogs() {
    const container = document.getElementById('logs-list');
    
    if (state.logs.length === 0) {
        container.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--text-muted);">暂无日志</div>';
        return;
    }
    
    container.innerHTML = state.logs.map(log => `
        <div class="log-item">
            <span class="log-time">${formatDate(log.created_at)}</span>
            <span class="log-type ${log.operation_type}">${log.operation_type}</span>
            <span class="log-content">
                ${log.target_email ? `[${log.target_email}] ` : ''}${log.details || ''}
            </span>
        </div>
    `).join('');
}

// ==================== Settings ====================
async function loadSettings() {
    try {
        const settings = await api.get('/api/settings');
        
        // 填充设置表单
        Object.entries(settings).forEach(([key, value]) => {
            const input = document.getElementById(`setting-${key}`);
            if (input) {
                input.value = value || '';
            }
        });
    } catch (error) {
        showToast('加载设置失败', 'error');
    }
}

async function saveSettings() {
    const settings = {};
    
    document.querySelectorAll('[id^="setting-"]').forEach(input => {
        const key = input.id.replace('setting-', '');
        settings[key] = input.value;
    });
    
    try {
        await api.post('/api/settings/save', settings);
        showToast('设置已保存', 'success');
    } catch (error) {
        showToast(`保存失败: ${error.message}`, 'error');
    }
}

// ==================== 快速操作 ====================
async function syncBrowsers() {
    try {
        const result = await api.post('/api/accounts/sync-browsers', {});
        showToast(result.message || '同步任务已启动', 'success');
    } catch (error) {
        showToast(`同步失败: ${error.message}`, 'error');
    }
}

async function exportFiles() {
    try {
        const result = await api.post('/api/export/files', {});
        showToast(result.message || '导出成功', 'success');
    } catch (error) {
        showToast(`导出失败: ${error.message}`, 'error');
    }
}

function toggleSecrets() {
    state.showSecrets = !state.showSecrets;
    
    // 更新按钮文字和图标
    const icon = document.getElementById('toggle-secrets-icon');
    const text = document.getElementById('toggle-secrets-text');
    
    if (state.showSecrets) {
        icon.textContent = '👁️';
        text.textContent = '隐藏密码';
    } else {
        icon.textContent = '🙈';
        text.textContent = '显示密码';
    }
    
    // 刷新当前页面的表格
    if (state.currentPage === 'accounts') {
        renderAccountsTable();
    } else if (state.currentPage === 'cards') {
        renderCardsTable();
    }
}

function refreshData() {
    switch (state.currentPage) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'accounts':
            loadAccounts();
            break;
        case 'proxies':
            loadProxies();
            break;
        case 'cards':
            loadCards();
            break;
        case 'logs':
            loadLogs();
            break;
    }
    showToast('数据已刷新', 'info');
}

// ==================== Modal ====================
function showModal(name) {
    const modal = document.getElementById(`modal-${name}`);
    const overlay = document.getElementById('modal-overlay');
    
    if (modal && overlay) {
        modal.classList.add('active');
        overlay.classList.add('active');
    }
}

function closeModal() {
    document.querySelectorAll('.modal').forEach(m => m.classList.remove('active'));
    document.getElementById('modal-overlay').classList.remove('active');
}

// ESC 关闭模态框
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeModal();
    }
});

// ==================== Toast ====================
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    
    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️',
    };
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || icons.info}</span>
        <span class="toast-message">${message}</span>
    `;
    
    container.appendChild(toast);
    
    // 自动移除
    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ==================== 工具函数 ====================
function getStatusLabel(status) {
    const labels = {
        'pending_check': '待检查',
        'link_ready': '链接就绪',
        'verified': '已验证',
        'subscribed': '已订阅',
        'ineligible': '无资格',
        'error': '错误',
        'running': '运行中',
        'processing': '处理中',
    };
    return labels[status] || status || '未知';
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function copyToClipboard(text) {
    if (!text) return;
    
    navigator.clipboard.writeText(text).then(() => {
        showToast('已复制到剪贴板', 'success');
    }).catch(() => {
        // Fallback
        const textarea = document.createElement('textarea');
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        showToast('已复制到剪贴板', 'success');
    });
}

// ==================== 键盘快捷键 ====================
document.addEventListener('keydown', (e) => {
    // Ctrl+R 刷新数据
    if (e.ctrlKey && e.key === 'r') {
        e.preventDefault();
        refreshData();
    }
    
    // 数字键快速导航
    if (e.altKey) {
        switch (e.key) {
            case '1': navigateTo('dashboard'); break;
            case '2': navigateTo('accounts'); break;
            case '3': navigateTo('proxies'); break;
            case '4': navigateTo('cards'); break;
            case '5': navigateTo('logs'); break;
            case '6': navigateTo('settings'); break;
        }
    }
});
