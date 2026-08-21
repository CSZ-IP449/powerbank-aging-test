# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件 exe（与充电柜监控桌面版一致的 onefile 方案）。

产物：backend/dist/aging-test.exe —— 单文件双击即可运行，前端 dist、后端、依赖全在里面。

前置：
  1. cd frontend && npm install && npm run build
  2. pip install pyinstaller pywebview flask flask-cors pyserial
打包：
  cd backend && pyinstaller desktop.spec --noconfirm --clean
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all

BACKEND_DIR = os.path.dirname(os.path.abspath(SPEC))
FRONTEND_DIST = os.path.normpath(os.path.join(BACKEND_DIR, '..', 'frontend', 'dist'))
ICON_PATH = os.path.join(BACKEND_DIR, 'aging-test.ico')

# 前端资源：整个 frontend/dist 打进 _MEIPASS/dist
datas = []
if os.path.isdir(FRONTEND_DIST):
    datas.append((FRONTEND_DIST, 'dist'))
else:
    print(f'[desktop.spec] 警告：未找到前端构建目录：{FRONTEND_DIST}')
    print('               请先在 frontend 目录执行 npm run build')

binaries = []
hiddenimports = []

# libffi DLL（ctypes/pythonnet 依赖，之前监控项目已验证）
_libffi_candidates = [
    os.path.join(os.path.dirname(sys.executable), 'DLLs', 'libffi-8.dll'),
    os.path.join(os.path.dirname(sys.executable), 'DLLs', 'libffi-7.dll'),
]
for _p in _libffi_candidates:
    if os.path.exists(_p):
        binaries.append((_p, '.'))
        break

# 完整收集依赖（与之前监控项目同样的策略，避免 hiddenimports 漏写导致打包后 ImportError）
def _collect(pkg):
    tmp = collect_all(pkg)
    datas.extend(tmp[0])
    binaries.extend(tmp[1])
    hiddenimports.extend(tmp[2])

_collect('flask')
_collect('flask_cors')
_collect('serial')      # pyserial
_collect('webview')     # pywebview

# pywebview + pythonnet + cffi 是调用 .NET WebView2 的铁三角
hiddenimports += [
    'pythonnet',
    'clr_loader',
    'cffi',
    'webview.platforms.edgechromium',
]
# tkinter 用于启动失败弹窗（Windows 自带）
hiddenimports += [
    'tkinter',
    'tkinter.messagebox',
    'tkinter.ttk',
]
# urllib 用于端口探活（onefile 有时会漏）
hiddenimports += [
    'urllib',
    'urllib.request',
]

a = Analysis(
    ['desktop.py'],
    pathex=[BACKEND_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter.test',
        'unittest',
        'pytest',
        'matplotlib',
        'numpy',
        'pandas',
        'PySide6',
        'PyQt5',
        'PyQt6',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='aging-test',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
)
