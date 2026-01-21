"""
@file main.py
@brief 程序主入口
@details Auto_All_System_Pyqt 应用程序入口点
"""
import sys
import os
import subprocess
import threading

# 确保src目录在路径中
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# 确保_legacy目录也在路径中（兼容旧模块）
LEGACY_DIR = os.path.join(SRC_DIR, '_legacy')
if LEGACY_DIR not in sys.path:
    sys.path.insert(0, LEGACY_DIR)

# 初始化核心模块
try:
    from core.database import DBManager
except ImportError:
    from database import DBManager

DBManager.init_db()

# 全局Web服务器进程
_web_server_process = None


def start_web_server(port=8080):
    """
    @brief 在后台线程启动Web服务器
    @param port 服务器端口
    @return 是否成功启动
    """
    global _web_server_process
    
    if _web_server_process and _web_server_process.poll() is None:
        print("[Web服务器] 已在运行中")
        return True
    
    try:
        # 查找server.py路径
        server_paths = [
            os.path.join(SRC_DIR, 'web', 'server.py'),
            os.path.join(SRC_DIR, 'web_admin', 'server.py'),
            os.path.join(os.path.dirname(SRC_DIR), 'web', 'server.py'),
        ]
        
        server_path = None
        for path in server_paths:
            if os.path.exists(path):
                server_path = path
                break
        
        if not server_path:
            print("[Web服务器] 未找到server.py文件")
            return False
        
        # 启动子进程
        python_exe = sys.executable
        _web_server_process = subprocess.Popen(
            [python_exe, server_path, '--port', str(port)],
            cwd=os.path.dirname(server_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        print(f"[Web服务器] 已启动，端口: {port}, PID: {_web_server_process.pid}")
        return True
        
    except Exception as e:
        print(f"[Web服务器] 启动失败: {e}")
        return False


def stop_web_server():
    """
    @brief 停止Web服务器
    """
    global _web_server_process
    
    if _web_server_process:
        try:
            _web_server_process.terminate()
            _web_server_process.wait(timeout=5)
            print("[Web服务器] 已停止")
        except:
            _web_server_process.kill()
        _web_server_process = None


def is_web_server_running():
    """
    @brief 检查Web服务器是否在运行
    @return 是否运行中
    """
    global _web_server_process
    return _web_server_process and _web_server_process.poll() is None


def run_gui():
    """
    @brief 运行主GUI界面
    """
    from PyQt6.QtWidgets import QApplication
    
    # 使用新的主窗口
    try:
        from gui.main_window import MainWindow
    except ImportError:
        # 回退到旧版
        try:
            from google.frontend import BrowserWindowCreatorGUI as MainWindow
        except ImportError:
            from create_window_gui import BrowserWindowCreatorGUI as MainWindow
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def run_web_admin(port=8080):
    """
    @brief 运行Web管理界面
    @param port 服务器端口
    """
    try:
        from web.server import run_server
    except ImportError:
        try:
            from web_admin.server import run_server
        except ImportError:
            print("[警告] web_admin 模块导入失败: No module named 'web_admin'")
            return
    
    run_server(port)


def main():
    """
    @brief 主函数
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Auto All System PyQt')
    parser.add_argument('--web', action='store_true', help='启动Web管理界面')
    parser.add_argument('--port', type=int, default=8080, help='Web服务器端口')
    
    args = parser.parse_args()
    
    if args.web:
        run_web_admin(args.port)
    else:
        run_gui()


if __name__ == '__main__':
    main()


