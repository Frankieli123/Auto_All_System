"""
创建比特浏览器新窗口
根据示例窗口的参数创建新窗口，从accounts.txt读取账户信息
"""
import requests
import json
import os
import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from backend_config import is_geekez_backend, get_bitbrowser_api_url, get_geekez_api_url

# 比特浏览器API地址
url = get_bitbrowser_api_url()
headers = {'Content-Type': 'application/json'}


def read_proxies(file_path: str) -> list:
    """
    读取代理信息文件
    
    Args:
        file_path: 代理文件路径
        
    Returns:
        代理列表，每个代理为字典格式 {'type': 'socks5', 'host': '', 'port': '', 'username': '', 'password': ''}
        如果没有代理则返回空列表
    """
    proxies = []
    
    if not os.path.exists(file_path):
        return proxies
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                match = re.match(r'^(socks5|http|https)://([^:]+):([^@]+)@([^:]+):(\d+)$', line)
                if match:
                    proxies.append({
                        'type': match.group(1),
                        'host': match.group(4),
                        'port': match.group(5),
                        'username': match.group(2),
                        'password': match.group(3),
                        'raw': line,
                    })
                else:
                    # GeekEZ 支持多协议（vmess/vless/trojan/...），这里保留原始字符串供后端使用
                    proxies.append({'raw': line})
    except Exception:
        pass
    
    return proxies


def read_separator_config(file_path: str) -> str:
    """
    从文件顶部读取分隔符配置
    
    格式: 分隔符="----"
    
    Returns:
        分隔符字符串，默认为 "----"
    """
    default_sep = "----"
    
    if not os.path.exists(file_path):
        return default_sep
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # 查找分隔符配置行
                if line.startswith('分隔符=') or line.startswith('separator='):
                    # 提取引号内的内容
                    import re
                    match = re.search(r'["\'](.+?)["\']', line)
                    if match:
                        return match.group(1)
                # 如果遇到非注释、非配置行，停止搜索
                if not line.startswith('#') and '=' not in line:
                    break
    except Exception:
        pass
    
    return default_sep


def parse_account_line(line: str, separator: str) -> dict:
    """
    根据指定分隔符解析账号信息行
    
    Args:
        line: 账号信息行
        separator: 分隔符
        
    Returns:
        解析后的账号字典
    """
    # 移除注释
    if '#' in line:
        comment_pos = line.find('#')
        line = line[:comment_pos].strip()
    
    if not line:
        return None
    
    # 使用指定分隔符分割
    parts = line.split(separator)
    parts = [p.strip() for p in parts if p.strip()]
    
    if len(parts) < 2:
        return None
    
    result = {
        'email': '',
        'password': '',
        'backup_email': '',
        '2fa_secret': '',
        'full_line': line
    }
    
    # 支持两种常见格式：
    # 1) 邮箱----密码----辅助邮箱----2FA密钥
    # 2) 邮箱----密码----2FA密钥（无辅助邮箱）
    if len(parts) >= 1:
        result['email'] = parts[0]
    if len(parts) >= 2:
        result['password'] = parts[1]

    if len(parts) >= 4:
        result['backup_email'] = parts[2]
        result['2fa_secret'] = parts[3]
    elif len(parts) == 3:
        third = parts[2]
        if '@' in third and '.' in third:
            result['backup_email'] = third
        else:
            result['2fa_secret'] = third

    return result if result['email'] else None


def read_accounts(file_path: str) -> list:
    """
    读取账户信息文件（使用配置的分隔符）
    
    文件格式：
    第一行（可选）：分隔符="----"
    后续行：邮箱[分隔符]密码[分隔符]辅助邮箱[分隔符]2FA密钥
    
    Args:
        file_path: 账户文件路径
        
    Returns:
        账户列表，每个账户为字典格式
    """
    accounts = []
    
    if not os.path.exists(file_path):
        print(f"错误: 找不到文件 {file_path}")
        return accounts
    
    # 读取分隔符配置
    separator = read_separator_config(file_path)
    print(f"使用分隔符: '{separator}'")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue
                
                # 跳过配置行
                if line.startswith('分隔符=') or line.startswith('separator='):
                    continue
                
                account = parse_account_line(line, separator)
                if account:
                    accounts.append(account)
                else:
                    print(f"警告: 第{line_num}行格式不正确: {line[:50]}")
    except Exception as e:
        print(f"读取文件出错: {e}")
    
    return accounts


def get_browser_list(page: int = 0, pageSize: int = 50):
    """
    获取所有窗口列表（使用POST请求，JSON body传参）
    
    Args:
        page: 页码，默认为1
        pageSize: 每页数量，默认为50
    
    Returns:
        窗口列表
    """
    if is_geekez_backend():
        try:
            base = get_geekez_api_url().rstrip('/')
            res = requests.get(f"{base}/profiles", timeout=5).json()
            if res.get('success') is True:
                profiles = (res.get('data') or {}).get('list') or []
                if pageSize and pageSize > 0:
                    start = page * pageSize
                    end = start + pageSize
                    return profiles[start:end]
                return profiles
        except Exception:
            return []

    try:
        json_data = {
            'page': page,
            'pageSize': pageSize
        }
        
        response = requests.post(
            f"{url}/browser/list",
            json=json_data,
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            res = response.json()
            if res.get('code') == 0 or res.get('success') == True:
                data = res.get('data', {})
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return data.get('list', [])
        return []
    except Exception:
        return []


def get_browser_info(browser_id: str):
    """
    获取指定窗口的详细信息
    
    Args:
        browser_id: 窗口ID
        
    Returns:
        窗口信息字典
    """
    browsers = get_browser_list()
    for browser in browsers:
        if browser.get('id') == browser_id:
            return browser
    return None


def delete_browsers_by_name(name_pattern: str):
    """
    根据名称删除所有匹配的窗口
    
    Args:
        name_pattern: 窗口名称（精确匹配）
        
    Returns:
        删除的窗口数量
    """
    if is_geekez_backend():
        browsers = get_browser_list(page=0, pageSize=100000)
        deleted_count = 0
        for browser in browsers:
            if browser.get('name') == name_pattern:
                if delete_browser_by_id(str(browser.get('id', ''))):
                    deleted_count += 1
        return deleted_count

    browsers = get_browser_list()
    deleted_count = 0
    
    for browser in browsers:
        if browser.get('name') == name_pattern:
            browser_id = browser.get('id')
            try:
                res = requests.post(
                    f"{url}/browser/delete",
                    json={'id': browser_id},
                    headers=headers,
                    timeout=10
                ).json()
                
                if res.get('code') == 0 or res.get('success') == True:
                    deleted_count += 1
            except Exception:
                pass
    
    return deleted_count


def open_browser_by_id(browser_id: str):
    """
    打开指定ID的窗口
    
    Args:
        browser_id: 窗口ID
        
    Returns:
        bool: 是否调用成功
    """
    if is_geekez_backend():
        try:
            base = get_geekez_api_url().rstrip('/')
            res = requests.post(
                f"{base}/profiles/{browser_id}/open",
                json={"watermarkStyle": "enhanced"},
                headers=headers,
                timeout=30,
            ).json()
            return res.get('success') is True
        except Exception:
            return False

    try:
        res = requests.post(
            f"{url}/browser/open",
            json={'id': browser_id},
            headers=headers,
            timeout=30
        ).json()
        
        if res.get('code') == 0 or res.get('success') == True:
            return True
    except Exception:
        pass
    return False


def delete_browser_by_id(browser_id: str):
    """
    删除指定ID的窗口
    
    Args:
        browser_id: 窗口ID
        
    Returns:
        bool: 是否删除成功
    """
    if is_geekez_backend():
        try:
            base = get_geekez_api_url().rstrip('/')
            res = requests.delete(f"{base}/profiles/{browser_id}", timeout=30).json()
            return res.get('success') is True
        except Exception:
            return False

    try:
        res = requests.post(
            f"{url}/browser/delete",
            json={'id': browser_id},
            headers=headers,
            timeout=10
        ).json()
        
        if res.get('code') == 0 or res.get('success') == True:
            return True
    except Exception:
        pass
    return False


def get_next_window_name(prefix: str):
    """
    根据前缀生成下一个窗口名称，格式：前缀_序号
    
    Args:
        prefix: 窗口名称前缀
        
    Returns:
        下一个窗口名称，如 "美国_1"
    """
    browsers = get_browser_list()
    max_num = 0
    
    # 遍历所有窗口，找到匹配前缀的最大序号
    prefix_pattern = f"{prefix}_"
    for browser in browsers:
        name = browser.get('name', '')
        if name == prefix: # 精确匹配前缀（视为序号0或1，视情况而定，这里假设如果不带序号算占用）
             pass # 简单起见，我们只看带下划线的，或者如果只有前缀，我们从1开始
             
        if name.startswith(prefix_pattern):
            try:
                # 尝试提取后缀数字
                suffix = name[len(prefix_pattern):]
                num = int(suffix)
                if num > max_num:
                    max_num = num
            except:
                pass
    
    return f"{prefix}_{max_num + 1}"


def open_browser_url(browser_id: str, target_url: str):
    """打开浏览器窗口并导航到指定URL"""
    try:
        res = requests.post(
            f"{url}/browser/open",
            json={"id": browser_id},
            headers=headers,
            timeout=30
        ).json()
        
        if res.get('code') == 0 or res.get('success') == True:
            driver_path = res.get('data', {}).get('driver')
            debugger_address = res.get('data', {}).get('http')
            
            if driver_path and debugger_address:
                try:
                    chrome_options = Options()
                    chrome_options.add_experimental_option("debuggerAddress", debugger_address)
                    chrome_service = Service(driver_path)
                    driver = webdriver.Chrome(service=chrome_service, options=chrome_options)
                    driver.get(target_url)
                    time.sleep(2)
                    driver.quit()
                except Exception:
                    pass
    except Exception:
        pass


def create_browser_window(account: dict, reference_browser_id: str = None, proxy: dict = None, platform: str = None, extra_url: str = None, name_prefix: str = None, template_config: dict = None):
    """
    创建新的浏览器窗口
    
    Args:
        account: 账户信息
        reference_browser_id: 参考窗口ID
        proxy: 代理信息
        platform: 平台URL
        extra_url: 额外URL
        name_prefix: 窗口名称前缀
        template_config: 直接提供的模板配置字典 (优先级高于 reference_browser_id)
        
    Returns:
        (browser_id, error_message)
    """
    if is_geekez_backend():
        try:
            base = get_geekez_api_url().rstrip('/')

            # 确定窗口名称前缀
            if name_prefix:
                final_prefix = name_prefix
            else:
                ref_name = ''
                if isinstance(template_config, dict):
                    ref_name = str(template_config.get('name', '') or '')
                if not ref_name and reference_browser_id:
                    ref = get_browser_info(reference_browser_id)
                    if ref:
                        ref_name = str(ref.get('name', '') or '')
                if '_' in ref_name:
                    ref_name = '_'.join(ref_name.split('_')[:-1])
                final_prefix = ref_name or 'GeekEZ'

            window_name = get_next_window_name(final_prefix)

            # 代理字符串：优先使用 raw（支持 vmess/vless/trojan/...）
            proxy_str = ''
            if proxy:
                proxy_str = str(proxy.get('raw', '') or '').strip()
                if not proxy_str and proxy.get('host') and proxy.get('port'):
                    t = proxy.get('type', 'socks5')
                    u = proxy.get('username', '')
                    p = proxy.get('password', '')
                    h = proxy.get('host', '')
                    port = proxy.get('port', '')
                    if u:
                        proxy_str = f"{t}://{u}:{p}@{h}:{port}"
                    else:
                        proxy_str = f"{t}://{h}:{port}"

            # 模板指纹：GeekEZ profile 使用 fingerprint 字段
            fingerprint = None
            ref_fp = None
            if isinstance(template_config, dict):
                ref_fp = template_config.get('fingerprint')
            if not ref_fp and reference_browser_id:
                ref = get_browser_info(reference_browser_id)
                if isinstance(ref, dict):
                    ref_fp = ref.get('fingerprint')
            if isinstance(ref_fp, dict) and ref_fp:
                fingerprint = ref_fp

            # 检查是否已存在该账号的窗口（基于 remark 中的邮箱）
            email = (account.get('email') or '').strip()
            if email:
                all_profiles = get_browser_list(page=0, pageSize=100000)
                for b in all_profiles:
                    r = str(b.get('remark', '') or '')
                    if r.startswith(email) or (email in r):
                        return None, f"该账号已有对应窗口: {b.get('name')} (ID: {b.get('id')})"

            payload = {
                'name': window_name,
                'proxyStr': proxy_str,
                'remark': account.get('full_line', ''),
            }
            if fingerprint is not None:
                payload['fingerprint'] = fingerprint

            res = requests.post(f"{base}/profiles", json=payload, headers=headers, timeout=10).json()
            if res.get('success') is True:
                browser_id = (res.get('data') or {}).get('id')
                if browser_id:
                    return browser_id, None
                return None, "创建成功但未返回ID"

            error_msg = res.get('error') or res.get('msg') or '未知API错误'
            return None, f"创建请求被拒绝: {error_msg}"
        except Exception as e:
            return None, f"请求异常: {str(e)}"

    if template_config:
        reference_config = template_config
    elif reference_browser_id:
        reference_config = get_browser_info(reference_browser_id)
        if not reference_config:
            return None, f"找不到参考窗口: {reference_browser_id}"
    else:
        return None, "未指定参考窗口ID或模板配置"
    
    json_data = {}
    exclude_fields = {'id', 'name', 'remark', 'userName', 'password', 'faSecretKey', 'createTime', 'updateTime'}
    
    for key, value in reference_config.items():
        if key not in exclude_fields:
            json_data[key] = value
    
    # 确定窗口名称
    if name_prefix:
        final_prefix = name_prefix
    else:
        # 如果未指定前缀，尝试从参考窗口名称推断
        ref_name = reference_config.get('name', '')
        if '_' in ref_name:
            final_prefix = '_'.join(ref_name.split('_')[:-1])
        else:
            final_prefix = ref_name
            
    json_data['name'] = get_next_window_name(final_prefix)
    json_data['remark'] = account['full_line']
    
    if platform:
        json_data['platform'] = platform
    if extra_url:
        json_data['url'] = extra_url
    
    if account.get('email'):
        json_data['userName'] = account['email']
    if account.get('password'):
        json_data['password'] = account['password']
    if account.get('2fa_secret') and account['2fa_secret'].strip():
        json_data['faSecretKey'] = account['2fa_secret'].strip()
    
    if 'browserFingerPrint' not in json_data:
        json_data['browserFingerPrint'] = {}
    
    if 'browserFingerPrint' in reference_config:
        ref_fp = reference_config['browserFingerPrint']
        if isinstance(ref_fp, dict):
            for key, value in ref_fp.items():
                if key != 'id':
                    json_data['browserFingerPrint'][key] = value
    
    json_data['browserFingerPrint']['coreVersion'] = '140'
    json_data['browserFingerPrint']['version'] = '140'
    
    if proxy and proxy.get('type') and proxy.get('host') and proxy.get('port'):
        json_data['proxyType'] = proxy.get('type')
        json_data['proxyMethod'] = 2
        json_data['host'] = proxy.get('host')
        json_data['port'] = proxy.get('port')
        json_data['proxyUserName'] = proxy.get('username', '')
        json_data['proxyPassword'] = proxy.get('password', '')
    else:
        json_data['proxyType'] = 'noproxy'
        json_data['proxyMethod'] = 2
        json_data['host'] = ''
        json_data['port'] = ''
        json_data['proxyUserName'] = ''
        json_data['proxyPassword'] = ''
    
    
    # 检查是否已存在该账号的窗口
    all_browsers = get_browser_list()
    for b in all_browsers:
        if b.get('userName') == account['email']:
            return None, f"该账号已有对应窗口: {b.get('name')} (ID: {b.get('id')})"

    try:
        res = requests.post(
            f"{url}/browser/update",
            json=json_data,
            headers=headers,
            timeout=10
        ).json()
        
        if res.get('code') == 0 or res.get('success') == True:
            browser_id = res.get('data', {}).get('id')
            if not browser_id:
                return None, "API返回成功但未获取到ID"
            
            created_config = get_browser_info(browser_id)
            need_update = False
            if created_config:
                if created_config.get('userName') != account['email']:
                    need_update = True
                if created_config.get('password') != account['password']:
                    need_update = True
                if account.get('2fa_secret') and account['2fa_secret'].strip():
                    if created_config.get('faSecretKey') != account['2fa_secret'].strip():
                        need_update = True
            
            if need_update or 'userName' not in json_data:
                update_data = {
                    'ids': [browser_id],
                    'userName': account['email'],
                    'password': account['password']
                }
                
                if account.get('2fa_secret') and account['2fa_secret'].strip():
                    update_data['faSecretKey'] = account['2fa_secret'].strip()
                
                try:
                    update_res = requests.post(
                        f"{url}/browser/update/partial",
                        json=update_data,
                        headers=headers,
                        timeout=10
                    ).json()
                    
                    if not (update_res.get('code') == 0 or update_res.get('success') == True):
                        if 'faSecretKey' in update_data:
                            retry_data = {
                                'ids': [browser_id],
                                'userName': account['email'],
                                'password': account['password']
                            }
                            requests.post(
                                f"{url}/browser/update/partial",
                                json=retry_data,
                                headers=headers,
                                timeout=10
                            )
                except Exception:
                    pass
            
            if account.get('2fa_secret') and account['2fa_secret'].strip():
                verify_config = get_browser_info(browser_id)
                if not (verify_config and verify_config.get('faSecretKey') == account['2fa_secret'].strip()):
                    try:
                        twofa_data = {
                            'ids': [browser_id],
                            'faSecretKey': account['2fa_secret'].strip()
                        }
                        requests.post(
                            f"{url}/browser/update/partial",
                            json=twofa_data,
                            headers=headers,
                            timeout=10
                        )
                    except Exception:
                        pass
            
            return browser_id, None
        
        error_msg = res.get('msg', '未知API错误')
        return None, f"创建请求被拒绝: {error_msg}"
        
    except Exception as e:
        return None, f"请求异常: {str(e)}"


def print_browser_info(browser_id: str):
    """打印窗口的完整配置信息"""
    config = get_browser_info(browser_id)
    if config:
        print(json.dumps(config, indent=2, ensure_ascii=False))


def main():
    accounts_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'accounts.txt')
    accounts = read_accounts(accounts_file)
    
    if not accounts:
        return
    
    proxies_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'proxies.txt')
    proxies = read_proxies(proxies_file)
    
    browsers = get_browser_list()
    if not browsers:
        return
    
    reference_browser_id = "4964d1fe7e584e868f14975f4c22e106"
    reference_config = get_browser_info(reference_browser_id)
    if not reference_config:
        browsers = get_browser_list()
        if browsers:
            reference_browser_id = browsers[0].get('id')
        else:
            return
    
    success_count = 0
    for i, account in enumerate(accounts, 1):
        proxy = proxies[i - 1] if i - 1 < len(proxies) else None
        browser_id, error = create_browser_window(account, reference_browser_id, proxy)
        if browser_id:
            success_count += 1
        else:
            print(f"窗口创建失败: {error}")
        if i < len(accounts):
            time.sleep(1)
    
    print(f"完成: {success_count}/{len(accounts)}")


if __name__ == "__main__":
    main()

