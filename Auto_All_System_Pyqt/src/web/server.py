"""
@file server.py
@brief Web Admin 服务器
@details 提供账号、代理、卡片的Web管理界面（支持多业务扩展）
"""
import http.server
import socketserver
import json
import os
import sys
import urllib.parse
from typing import Dict, Any, List

# 获取当前目录
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# 添加src目录到路径
_src_dir = os.path.dirname(CURRENT_DIR)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# 导入核心模块
try:
    from core.database import DBManager
except ImportError:
    from database import DBManager

# 配置路径
PORT = 8080
TEMPLATE_DIR = os.path.join(CURRENT_DIR, 'templates')
STATIC_DIR = os.path.join(CURRENT_DIR, 'static')


class APIHandler(http.server.SimpleHTTPRequestHandler):
    """
    @class APIHandler
    @brief HTTP请求处理器
    @details 处理Web管理界面的所有HTTP请求，支持RESTful API
    """
    
    # 业务类型配置（可扩展）
    BUSINESS_TYPES = {
        'google': {'name': 'Google', 'icon': '🔵', 'color': '#4285f4'},
        'facebook': {'name': 'Facebook', 'icon': '🔷', 'color': '#1877f2'},
        'twitter': {'name': 'Twitter/X', 'icon': '⬛', 'color': '#000000'},
        'microsoft': {'name': 'Microsoft', 'icon': '🟦', 'color': '#00a4ef'},
        'apple': {'name': 'Apple', 'icon': '⚪', 'color': '#555555'},
    }
    
    def log_message(self, format, *args):
        """静默日志"""
        pass
    
    def send_json(self, data: Any, status: int = 200):
        """发送JSON响应"""
        self.send_response(status)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str, ensure_ascii=False).encode('utf-8'))
    
    def send_html(self, file_path: str):
        """发送HTML文件"""
        if not os.path.exists(file_path):
            self.send_error(404, "Page not found")
            return
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        with open(file_path, 'rb') as f:
            self.wfile.write(f.read())

    def send_static(self, file_path: str):
        """发送静态文件"""
        if not os.path.exists(file_path):
            self.send_error(404)
            return
        
        ext = os.path.splitext(file_path)[1].lower()
        content_types = {
            '.css': 'text/css; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon',
            '.woff': 'font/woff',
            '.woff2': 'font/woff2',
            '.ttf': 'font/ttf',
        }
        
        self.send_response(200)
        self.send_header('Content-type', content_types.get(ext, 'application/octet-stream'))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()
        with open(file_path, 'rb') as f:
            self.wfile.write(f.read())

    def do_OPTIONS(self):
        """处理CORS预检请求"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def do_GET(self):
        """处理GET请求"""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        
        # 页面路由
        if path == '/' or path == '/index.html':
            self.send_html(os.path.join(TEMPLATE_DIR, 'index.html'))
            return
        
        # 静态文件
        if path.startswith('/static/'):
            file_path = os.path.join(CURRENT_DIR, path[1:])
            self.send_static(file_path)
            return
        
        # ==================== 系统API ====================
        if path == '/api/system/info':
            self.send_json({
                'version': '2.0.0',
                'business_types': self.BUSINESS_TYPES
            })
            return
        
        if path == '/api/system/stats':
            stats = {
                'accounts': DBManager.get_accounts_count_by_status(),
                'total_accounts': len(DBManager.get_all_accounts()),
                'total_proxies': len(DBManager.get_all_proxies()),
                'available_proxies': len(DBManager.get_available_proxies()),
                'total_cards': len(DBManager.get_all_cards()),
                'available_cards': len(DBManager.get_available_cards()),
            }
            self.send_json(stats)
            return
        
        # ==================== 账号API ====================
        if path == '/api/accounts':
            status_filter = query.get('status', [None])[0]
            business_filter = query.get('business', [None])[0]
            
            if status_filter:
                accounts = DBManager.get_accounts_by_status(status_filter)
            else:
                accounts = DBManager.get_all_accounts()
            
            # TODO: 当数据库支持business字段后，添加业务过滤
            self.send_json({'data': accounts, 'total': len(accounts)})
            return
        
        if path == '/api/accounts/stats':
            stats = DBManager.get_accounts_count_by_status()
            self.send_json(stats)
            return
        
        # ==================== 代理API ====================
        if path == '/api/proxies':
            proxies = DBManager.get_all_proxies()
            self.send_json({'data': proxies, 'total': len(proxies)})
            return
        
        if path == '/api/proxies/available':
            proxies = DBManager.get_available_proxies()
            self.send_json({'data': proxies, 'total': len(proxies)})
            return
        
        # ==================== 卡片API ====================
        if path == '/api/cards':
            cards = DBManager.get_all_cards()
            self.send_json({'data': cards, 'total': len(cards)})
            return
        
        if path == '/api/cards/available':
            cards = DBManager.get_available_cards()
            self.send_json({'data': cards, 'total': len(cards)})
            return
        
        # ==================== 设置API ====================
        if path == '/api/settings':
            settings = DBManager.get_all_settings()
            self.send_json(settings)
            return
        
        # ==================== 日志API ====================
        if path == '/api/logs':
            limit = int(query.get('limit', [100])[0])
            logs = DBManager.get_recent_logs(limit)
            self.send_json({'data': logs, 'total': len(logs)})
            return

        self.send_error(404, "API not found")

    def do_POST(self):
        """处理POST请求"""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        # 读取请求体
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        
        try:
            params = json.loads(body.decode('utf-8')) if body else {}
        except json.JSONDecodeError:
            self.send_json({'success': False, 'error': 'Invalid JSON'}, 400)
            return
        
        # ==================== 账号操作 ====================
        if path == '/api/accounts/import':
            text = params.get('text', '')
            status = params.get('status', 'pending_check')
            separator = params.get('separator', '----')
            # business = params.get('business', 'google')  # 预留业务类型
            
            if not text.strip():
                self.send_json({'success': False, 'error': '请输入账号数据'}, 400)
                return
            
            success, errors, details = DBManager.import_accounts_from_text(text, separator, status)
            self.send_json({
                'success': True,
                'imported': success,
                'failed': errors,
                'errors': details[:10]
            })
            return
        
        if path == '/api/accounts/update':
            email = params.get('email')
            updates = params.get('updates', {})
            
            if not email:
                self.send_json({'success': False, 'error': '缺少邮箱'}, 400)
                return
            
            DBManager.upsert_account(
                email,
                password=updates.get('password'),
                recovery_email=updates.get('recovery_email'),
                secret_key=updates.get('secret_key'),
                status=updates.get('status'),
                message=updates.get('message')
            )
            self.send_json({'success': True})
            return
        
        if path == '/api/accounts/delete':
            emails = params.get('emails', [])
            if isinstance(emails, str):
                emails = [emails]
            
            deleted = 0
            for email in emails:
                try:
                    DBManager.delete_account(email)
                    deleted += 1
                except Exception:
                    pass
            
            self.send_json({'success': True, 'deleted': deleted})
            return
        
        if path == '/api/accounts/export':
            emails = set(params.get('emails', []))
            fields = params.get('fields', ['email', 'password', 'recovery_email', 'secret_key'])
            separator = params.get('separator', '----')
            status_filter = params.get('status', '')  # 状态筛选
            
            # 根据状态获取账号
            if status_filter:
                accounts = DBManager.get_accounts_by_status(status_filter)
            else:
                accounts = DBManager.get_all_accounts()
            
            lines = []
            
            for acc in accounts:
                if not emails or acc['email'] in emails:
                    parts = [str(acc.get(f) or '') for f in fields]
                    lines.append(separator.join(parts))
            
            self.send_json({'success': True, 'data': '\n'.join(lines), 'count': len(lines)})
            return
        
        if path == '/api/accounts/sync-browsers':
            try:
                DBManager.import_from_browsers()
                self.send_json({'success': True, 'message': '同步任务已启动'})
            except Exception as e:
                self.send_json({'success': False, 'error': str(e)}, 500)
            return
        
        # ==================== 代理操作 ====================
        if path == '/api/proxies/import':
            text = params.get('text', '')
            proxy_type = params.get('type', 'socks5')
            
            if not text.strip():
                self.send_json({'success': False, 'error': '请输入代理数据'}, 400)
                return
            
            success, errors, details = DBManager.import_proxies_from_text(text, proxy_type)
            self.send_json({
                'success': True,
                'imported': success,
                'failed': errors,
                'errors': details[:10]
            })
            return
        
        if path == '/api/proxies/delete':
            ids = params.get('ids', [])
            if isinstance(ids, int):
                ids = [ids]
            
            deleted = 0
            for pid in ids:
                try:
                    DBManager.delete_proxy(pid)
                    deleted += 1
                except Exception:
                    pass
            
            self.send_json({'success': True, 'deleted': deleted})
            return
        
        if path == '/api/proxies/clear':
            DBManager.clear_all_proxies()
            self.send_json({'success': True})
            return
        
        # ==================== 卡片操作 ====================
        if path == '/api/cards/import':
            text = params.get('text', '')
            max_usage = params.get('max_usage', 1)
            
            if not text.strip():
                self.send_json({'success': False, 'error': '请输入卡片数据'}, 400)
                return
            
            success, errors, details = DBManager.import_cards_from_text(text, max_usage)
            self.send_json({
                'success': True,
                'imported': success,
                'failed': errors,
                'errors': details[:10]
            })
            return

        if path == '/api/cards/update':
            card_id = params.get('id')
            if card_id is None:
                self.send_json({'success': False, 'error': '缺少卡片ID'}, 400)
                return

            try:
                card_id = int(card_id)
            except Exception:
                self.send_json({'success': False, 'error': '卡片ID无效'}, 400)
                return

            try:
                DBManager.update_card(
                    card_id,
                    exp_month=params.get('exp_month'),
                    exp_year=params.get('exp_year'),
                    cvv=params.get('cvv'),
                    holder_name=params.get('holder_name'),
                    zip_code=params.get('zip_code'),
                    country=params.get('country'),
                    state=params.get('state'),
                    city=params.get('city'),
                    address=params.get('address'),
                    max_usage=params.get('max_usage'),
                    is_active=params.get('is_active'),
                )
            except Exception as e:
                self.send_json({'success': False, 'error': str(e)}, 500)
                return

            self.send_json({'success': True})
            return
        
        if path == '/api/cards/delete':
            ids = params.get('ids', [])
            if isinstance(ids, int):
                ids = [ids]
            
            deleted = 0
            for cid in ids:
                try:
                    DBManager.delete_card(cid)
                    deleted += 1
                except Exception:
                    pass
            
            self.send_json({'success': True, 'deleted': deleted})
            return
        
        if path == '/api/cards/toggle':
            card_id = params.get('id')
            is_active = params.get('active', True)
            
            if card_id:
                DBManager.set_card_active(card_id, is_active)
                self.send_json({'success': True})
            else:
                self.send_json({'success': False, 'error': '缺少卡片ID'}, 400)
            return
        
        if path == '/api/cards/clear':
            DBManager.clear_all_cards()
            self.send_json({'success': True})
            return
        
        # ==================== 设置操作 ====================
        if path == '/api/settings/save':
            for key, value in params.items():
                DBManager.set_setting(key, str(value))
            self.send_json({'success': True})
            return
        
        # ==================== 数据导出 ====================
        if path == '/api/export/files':
            DBManager.export_to_files()
            self.send_json({'success': True, 'message': '已导出到data目录'})
            return
            
        self.send_json({'success': False, 'error': 'API not found'}, 404)


def run_server(port: int = 8080):
    """
    @brief 启动Web Admin服务器
    @param port 服务器端口
    """
    # 确保目录存在
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    os.makedirs(os.path.join(STATIC_DIR, 'css'), exist_ok=True)
    os.makedirs(os.path.join(STATIC_DIR, 'js'), exist_ok=True)
    
    # 初始化数据库
    DBManager.init_db()
    
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", port), APIHandler) as httpd:
            print(f"╔══════════════════════════════════════════╗")
            print(f"║   🚀 Web Admin Server Started            ║")
            print(f"║   📍 http://localhost:{port:<5}              ║")
            print(f"║   💡 Press Ctrl+C to stop                ║")
            print(f"╚══════════════════════════════════════════╝")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped.")
    except OSError as e:
        print(f"❌ Port {port} error: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Web Admin Server')
    parser.add_argument('-p', '--port', type=int, default=8080, help='Server port')
    args = parser.parse_args()
    run_server(args.port)
