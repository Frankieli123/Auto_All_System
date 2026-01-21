"""
@file worker_thread.py
@brief 后台工作线程模块
@details 提供QThread工作线程，避免阻塞主界面
"""

import time
from typing import Dict, List, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtCore import QThread, pyqtSignal


class WorkerThread(QThread):
    """
    @class WorkerThread
    @brief 通用后台工作线程
    @details 用于执行耗时任务，避免阻塞主界面
    """
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(dict)
    
    def __init__(self, task_type: str, **kwargs):
        """
        @brief 初始化工作线程
        @param task_type 任务类型: 'sheerlink', 'create', 'delete', 'open'
        @param kwargs 任务参数
        """
        super().__init__()
        self.task_type = task_type
        self.kwargs = kwargs
        self.is_running = True
    
    def stop(self):
        """停止任务"""
        self.is_running = False
    
    def log(self, message: str):
        """发送日志信号"""
        self.log_signal.emit(message)
    
    def msleep_safe(self, ms: int):
        """可中断的sleep"""
        t = ms
        while t > 0 and self.is_running:
            time.sleep(0.1)
            t -= 100
    
    def run(self):
        """执行任务"""
        if self.task_type == 'sheerlink':
            self.run_sheerlink()
        elif self.task_type == 'create':
            self.run_create()
        elif self.task_type == 'delete':
            self.run_delete()
        elif self.task_type == 'open':
            self.run_open()
    
    def run_sheerlink(self):
        """执行SheerLink提取任务 (多线程)"""
        ids_to_process = self.kwargs.get('ids', [])
        thread_count = self.kwargs.get('thread_count', 1)
        
        if not ids_to_process:
            self.finished_signal.emit({'type': 'sheerlink', 'count': 0})
            return
        
        self.log(f"\n[开始] 提取 SheerID Link，共 {len(ids_to_process)} 个窗口，并发: {thread_count}")
        
        # 统计计数
        stats = {
            'link_unverified': 0,
            'link_verified': 0,
            'subscribed': 0,
            'ineligible': 0,
            'timeout': 0,
            'error': 0
        }
        
        success_count = 0
        
        # 导入处理函数
        try:
            from google.backend.sheerlink_service import process_browser
        except ImportError as e:
            self.log(f"❌ 导入失败: {e}")
            self.finished_signal.emit({'type': 'sheerlink', 'count': 0, 'error': str(e)})
            return
        
        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            future_to_id = {}
            for bid in ids_to_process:
                if not self.is_running:
                    break
                # 回调函数
                callback = lambda msg, b=bid: self.log_signal.emit(f"[{b[:8]}...] {msg}")
                future = executor.submit(process_browser, bid, log_callback=callback)
                future_to_id[future] = bid
            
            finished_tasks = 0
            for future in as_completed(future_to_id):
                if not self.is_running:
                    self.log('[用户操作] 任务已停止')
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                
                bid = future_to_id[future]
                finished_tasks += 1
                try:
                    success, msg = future.result()
                    if success:
                        self.log(f"✅ ({finished_tasks}/{len(ids_to_process)}) {bid[:12]}...: {msg}")
                        success_count += 1
                    else:
                        self.log(f"❌ ({finished_tasks}/{len(ids_to_process)}) {bid[:12]}...: {msg}")
                    
                    # 统计分类
                    if "Verified" in msg or "Get Offer" in msg:
                        stats['link_verified'] += 1
                    elif "Link Found" in msg or "提取成功" in msg:
                        stats['link_unverified'] += 1
                    elif "Subscribed" in msg or "已绑卡" in msg:
                        stats['subscribed'] += 1
                    elif "无资格" in msg or "Not Available" in msg:
                        stats['ineligible'] += 1
                    elif "超时" in msg or "Timeout" in msg:
                        stats['timeout'] += 1
                    else:
                        stats['error'] += 1
                        
                except Exception as e:
                    self.log(f"❌ ({finished_tasks}/{len(ids_to_process)}) {bid[:12]}...: {e}")
                    stats['error'] += 1
        
        # 统计报告
        summary = (
            f"\n📊 任务统计报告:\n"
            f"--------------------------------\n"
            f"🔗 有资格待验证:   {stats['link_unverified']}\n"
            f"✅ 已过验证未绑卡: {stats['link_verified']}\n"
            f"💳 已过验证已绑卡: {stats['subscribed']}\n"
            f"❌ 无资格 (不可用): {stats['ineligible']}\n"
            f"⏳ 超时/错误:      {stats['timeout'] + stats['error']}\n"
            f"--------------------------------\n"
            f"总计处理: {finished_tasks}/{len(ids_to_process)}"
        )
        self.log(summary)
        self.finished_signal.emit({
            'type': 'sheerlink', 
            'count': success_count, 
            'stats': stats,
            'summary': summary
        })
    
    def run_create(self):
        """执行创建窗口任务"""
        # TODO: 实现创建窗口的后台任务
        self.finished_signal.emit({'type': 'create', 'count': 0})
    
    def run_delete(self):
        """执行删除窗口任务"""
        # TODO: 实现删除窗口的后台任务
        self.finished_signal.emit({'type': 'delete', 'count': 0})
    
    def run_open(self):
        """执行打开窗口任务"""
        # TODO: 实现打开窗口的后台任务
        self.finished_signal.emit({'type': 'open', 'count': 0})
