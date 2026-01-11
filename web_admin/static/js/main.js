let allAccounts = [];

document.addEventListener('DOMContentLoaded', () => {
    fetchAccounts();
    
    document.getElementById('searchInput').addEventListener('input', renderTable);
    document.querySelectorAll('.filter-cb').forEach(cb => cb.addEventListener('change', renderTable));
    
    document.getElementById('btnExport').addEventListener('click', showExportModal);
    document.getElementById('btnConfirmExport').addEventListener('click', confirmExport);
    document.getElementById('btnCancelExport').addEventListener('click', hideExportModal);
});

function fetchAccounts() {
    fetch('/api/accounts')
        .then(r => r.json())
        .then(data => {
            allAccounts = data;
            renderTable();
        })
        .catch(err => {
            console.error('加载数据失败:', err);
            document.getElementById('countDisplay').innerText = '加载失败，请检查后台服务';
        });
}

function renderTable() {
    const tbody = document.getElementById('accountTableBody');
    tbody.innerHTML = '';
    
    const search = document.getElementById('searchInput').value.toLowerCase();
    const activeStatues = Array.from(document.querySelectorAll('.filter-cb:checked')).map(cb => cb.value);
    
    const filtered = allAccounts.filter(acc => {
        if (activeStatues.length > 0 && !activeStatues.includes(acc.status)) return false;
        
        const term = search;
        if (!term) return true;
        
        return (acc.email || '').toLowerCase().includes(term) || 
               (acc.status || '').toLowerCase().includes(term);
    });
    
    document.getElementById('countDisplay').innerText = `显示 ${filtered.length} / ${allAccounts.length} 个账号`;

    filtered.forEach(acc => {
        const tr = document.createElement('tr');
        
        // 创建可点击复制的单元格
        tr.innerHTML = `
            <td class="copyable" data-value="${acc.email || ''}">${acc.email || '-'}</td>
            <td class="copyable" data-value="${acc.password || ''}">${acc.password || '-'}</td>
            <td class="copyable" data-value="${acc.recovery_email || ''}">${acc.recovery_email || '-'}</td>
            <td class="copyable" data-value="${acc.secret_key || ''}">${acc.secret_key || '-'}</td>
            <td class="copyable link-cell" data-value="${acc.verification_link || ''}" title="${acc.verification_link || ''}">${acc.verification_link || '-'}</td>
            <td><span class="status-badge status-${acc.status}">${mapStatus(acc.status)}</span></td>
        `;
        tbody.appendChild(tr);
    });
    
    // 为所有可复制单元格添加点击事件
    document.querySelectorAll('.copyable').forEach(cell => {
        cell.addEventListener('click', function() {
            const value = this.getAttribute('data-value');
            if (value && value !== '-' && value !== '') {
                copyToClipboard(value);
                showCopyFeedback(this);
            }
        });
    });
    
    window.currentFiltered = filtered; // For export
}

function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            console.log('已复制到剪贴板');
        }).catch(err => {
            console.error('复制失败:', err);
            fallbackCopy(text);
        });
    } else {
        fallbackCopy(text);
    }
}

function fallbackCopy(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
        console.log('已复制（兼容模式）');
    } catch (err) {
        console.error('复制失败:', err);
    }
    document.body.removeChild(textarea);
}

function showCopyFeedback(element) {
    const originalBg = element.style.backgroundColor;
    element.style.backgroundColor = '#d4edda';
    element.style.transition = 'background-color 0.2s';
    setTimeout(() => {
        element.style.backgroundColor = originalBg;
    }, 500);
}

function mapStatus(s) {
    const map = {
        'link_ready': '有资格待验证已提取链接',
        'verified': '已验证未绑卡',
        'subscribed': '已绑卡订阅',
        'ineligible': '无资格',
        'error': '错误/超时'
    };
    return map[s] || s;
}

function showExportModal() {
    document.getElementById('exportModal').style.display = 'block';
}

function hideExportModal() {
    document.getElementById('exportModal').style.display = 'none';
}

function confirmExport() {
    if (!window.currentFiltered || window.currentFiltered.length === 0) {
        alert("没有可导出的账号！");
        return;
    }
    
    const fields = Array.from(document.querySelectorAll('.export-field:checked')).map(cb => cb.value);
    const emails = window.currentFiltered.map(acc => acc.email);
    
    fetch('/api/export', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({emails, fields})
    })
    .then(res => res.blob())
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `exported_accounts_${new Date().getTime()}.txt`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        hideExportModal();
    })
    .catch(err => {
        console.error('导出失败:', err);
        alert('导出失败，请查看控制台日志');
    });
}
