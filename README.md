# 充电柜进出仓老化测试系统

充电柜与测试工装联动的进出仓老化测试桌面应用。基于 pywebview + React + Flask，通过 HDLC 协议与充电柜和测试工装通信，按「整柜出仓 → 整柜进仓」循环执行充电宝老化测试。

## 功能

- 双设备连接管理（充电柜 + 测试工装，各自独立 COM 口）
- 自动读取柜型与槽位数（支持 1~128 槽位）
- 整柜循环测试：每轮先全部出仓，再全部进仓，达标后跳过
- 出仓前预校验：检查 ID、锁扣、托盘、检测状态，异常时判定该轮失败但仍执行出仓
- 单槽 5 秒超时，失败可配置重试（默认 2 次）
- 实时显示槽位状态、充电宝 ID、三个按键状态、累计统计
- 出仓/进仓独立成功/失败计数
- 4 层日志（整轮 / 单槽 / 通信 / 操作）支持追溯
- 协议调试面板查看原始 HDLC 报文

## 技术栈

**前端**：React 18 + TypeScript + Vite + Tailwind CSS

**后端**：Python Flask + pyserial

**协议**：HDLC + CRC-16/CCITT-FALSE（充电柜 Address=0xA0，工装 Address=0xA1）

**桌面外壳**：pywebview（调用系统 Edge WebView2）

**打包**：PyInstaller（单文件 onefile 模式）

## 目录结构

```
aging-test-app/
├── frontend/               # React 前端
│   ├── src/
│   │   ├── components/     # 组件（槽位网格、协议调试、连接面板等）
│   │   ├── services/       # API 封装
│   │   ├── store/          # 全局状态管理
│   │   └── types/          # TypeScript 类型定义
│   ├── package.json
│   └── vite.config.ts
├── backend/                # Flask 后端
│   ├── app.py              # Flask 入口与 API 路由
│   ├── hdlc.py             # HDLC 协议帧解析与打包
│   ├── models.py           # 数据模型定义
│   ├── test_runner.py      # 测试流程状态机
│   ├── stats_store.py      # 统计数据持久化
│   ├── serial_bridge.py    # 双串口管理
│   ├── mock_backend.py     # Mock 数据后端
│   ├── app_logger.py       # 日志系统
│   ├── desktop.py          # 桌面版入口（pywebview）
│   ├── desktop.spec        # PyInstaller 配置
│   └── requirements.txt
├── 打包.bat                 # 一键打包脚本
└── README.md
```

## 开发运行

需要 Node.js 18+ 和 Python 3.10+。

**后端**：

```bash
cd backend
pip install -r requirements.txt
python app.py
```

后端启动后监听 `http://localhost:5174`。

**前端**：

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 `http://localhost:5175`。

## 工作模式

- **Mock 模式**：不依赖硬件，使用内置模拟数据，用于 UI 与流程开发
- **真实模式**：连接充电柜 COM 口 + 测试工装 COM 口（115200 / 8N1），通过 HDLC 通信

未连接硬件时自动降级到 Mock 数据并在界面上明确提示。

## 测试流程

1. App 启动后分别连接充电柜和测试工装
2. 通过 0x01 命令查询柜型与槽位数
3. 设置目标测试次数后启动测试
4. 整柜出仓阶段：逐槽发送 0x04 出仓命令，等待 0x02 上报最终状态
5. 间隔 3 秒后进入整柜进仓阶段：逐槽发送 0x03 给工装，工装响应后查 0x02 确认
6. 进仓完成且预校验均通过则该轮成功，`completed_test_count` 加 1
7. 未达标槽位继续循环，全部达标后结束

## 单槽超时

- 出仓：发送 0x04 起 5 秒
- 进仓：发送 0x03 起 5 秒（含工装响应 + 充电柜 0x02 确认）

## 成功判定

**出仓成功**：lock=0, tray=1, detect=1 且 id_ok=0

**进仓成功**：lock=0, tray=0, detect=0 且 id_ok=1 且 ID 与初始一致

**预校验规则**：出仓前需满足 id_ok=1、ID 与初始一致、锁扣=0、托盘=0、检测=0。不满足时判定该轮失败，但仍执行出仓动作。

## 协议命令

| 命令 | 对象 | 用途 |
|------|------|------|
| 0x01 | 充电柜 | 查询柜型与槽位数 |
| 0x02 | 充电柜 | 查询单槽状态（16 字节仓道数据块） |
| 0x03 | 测试工装 | 指定槽位进仓（响应 `[slot_no, status]`） |
| 0x04 | 充电柜 | 指定槽位出仓（响应 `[slot_no, status]`） |

## 日志

```
backend/logs/
├── rounds_YYYY-MM-DD.csv     # 整轮测试汇总
├── slots_YYYY-MM-DD.csv      # 单槽测试明细
├── comm_YYYY-MM-DD.log       # 通信原始报文
└── operations_YYYY-MM-DD.log # 操作与状态变迁
```

## 打包

桌面版打包为单文件 exe，使用 PyInstaller onefile + pywebview。

一键打包（Windows）：

```
双击 打包.bat
```

或手动执行：

```bash
cd frontend
npm install
npm run build               # 产出 frontend/dist

cd ../backend
pyinstaller desktop.spec --noconfirm --clean
# 产出 backend/dist/aging-test.exe
```

运行桌面版：直接执行 `backend/dist/aging-test.exe`。启动后自动创建 1400×900 桌面窗口，加载内置 Flask 服务。

> 打包前请确认 WebView2 Runtime 已安装（Windows 10 1803+ 通常已预装）。

## 运行时目录结构

```
aging-test.exe
├── data/               # 运行时数据目录（统计持久化）
└── logs/               # 运行时日志目录
```

首次启动时自动创建 `data/` 与 `logs/` 目录。

## 注意事项

- 同一 COM 口不允许两个进程同时打开，桌面版与其他串口相关程序不可同时运行
- 真实模式下需先在协议调试面板连接正确的串口设备
- 测试工装供电需稳定，无响应时进仓将触发超时判定
- 端口冲突时程序自动顺延（5001~5020），无需手动干预
- 杀毒软件可能误报 exe，需添加白名单