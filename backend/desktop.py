"""进出仓老化测试 - 桌面版入口
使用 pywebview + Flask，打包为单个 exe（onefile 模式）。
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import traceback

BACKEND_HOST = '127.0.0.1'
BACKEND_PORT = 5001
WINDOW_TITLE = '进出仓老化测试'
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900


def show_error(title: str, message: str):
    """使用系统自带 tkinter 弹窗，Windows 无需额外依赖"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        # 没有 tkinter 时打印到控制台（onefile console=False 时不可见，但至少不崩）
        print(f'[{title}] {message}')


def _find_free_port(preferred: int) -> int:
    """优先使用 preferred 端口，被占用则顺延"""
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((BACKEND_HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f'no free port in [{preferred}, {preferred + 20})')


def run_flask(port: int):
    """后台线程运行 Flask 后端"""
    try:
        from app import create_app
        flask_app = create_app()
        flask_app.run(host=BACKEND_HOST, port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        logging.getLogger(__name__).exception('Flask 启动失败')
        if getattr(sys, 'frozen', False):
            show_error('启动失败', f'服务启动失败：{e}\n\n详情：\n{traceback.format_exc()}')


def wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """用 HTTP 请求探活 Flask 服务，比 raw socket 更可靠"""
    import urllib.request
    deadline = time.monotonic() + timeout
    url = f'http://{BACKEND_HOST}:{port}/api/health'
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as r:
                if 200 <= r.status < 500:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def _check_frontend_dist() -> bool:
    """检查前端资源是否已内嵌（dist/index.html）"""
    bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    dist_index = os.path.join(bundle_dir, 'dist', 'index.html')
    return os.path.exists(dist_index)


def main():
    os.environ['PYWEBVIEW_DISABLE_ASSETS_WARNING'] = '1'

    # 开发模式下允许缺失 dist（直接走 404 JSON），打包后必须有
    if getattr(sys, 'frozen', False) and not _check_frontend_dist():
        show_error('启动失败', '前端资源文件未找到。\n请确认程序完整性，或重新执行打包步骤。')
        sys.exit(1)

    # 解析端口（5001 ~ 5020 自动顺延）
    try:
        port = _find_free_port(BACKEND_PORT)
    except RuntimeError as e:
        show_error('启动失败', f'无法找到可用端口：{e}')
        sys.exit(1)

    # 启动 Flask 后台线程
    server_thread = threading.Thread(target=run_flask, args=(port,), name='flask-server', daemon=True)
    server_thread.start()

    # 等待 HTTP 服务就绪
    if not wait_for_server(port, timeout=15.0):
        show_error(
            '启动警告',
            f'服务启动超时，窗口可能需要等待几秒。\n'
            f'如果长时间未响应，请关闭程序后确认端口 {port} 未被占用，再重新启动。',
        )

    import webview

    window_url = f'http://{BACKEND_HOST}:{port}/'
    webview.create_window(
        title=WINDOW_TITLE,
        url=window_url,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(1024, 700),
        resizable=True,
        text_select=True,
        confirm_close=False,
    )

    try:
        # gui='edgechromium' 可省略，但写出来避免 pywebview 选错引擎
        webview.start(debug=False, gui='edgechromium')
    except Exception as e:
        # WebView2 不可用时给出明确提示
        logging.getLogger(__name__).exception('pywebview 启动失败')
        show_error(
            '启动失败',
            f'桌面窗口引擎启动失败：{e}\n\n'
            '请安装 Microsoft Edge WebView2 Runtime：\n'
            'https://developer.microsoft.com/microsoft-edge/webview2/',
        )
        # 最后手段：尝试打开系统浏览器
        try:
            import webbrowser
            webbrowser.open(window_url)
            time.sleep(5)
        except Exception:
            pass


if __name__ == '__main__':
    main()
