# 进出仓老化测试 App

充电柜与测试工装联动的进出仓老化测试桌面应用。基于 pywebview + React + Flask，通过 HDLC 协议与充电柜和测试工装通信，按"整柜出仓 → 整柜进仓"循环执行充电宝老化测试。

## 功能

- 双设备连接管理（充电柜 + 测试工装，各自独立 COM 口）
- 自动读取柜型与槽位数（支持 1~128 槽位）
- 整柜循环测试：每轮先全部出仓，再全部进仓，达标后跳过
- 单槽 5 秒超时，失败可配置重试（默认 2 次）
- 实时显示槽位状态、充电宝 ID、三个按键状态、累计统计
- 4 层日志（整轮 / 单槽 / 通信 / 操作）支持追溯
- 协议调试面板查看原始报文

## 技术栈

- 前端：React 18 + TypeScript + Vite + Tailwind CSS
- 后端：Python Flask + pyserial
- 协议：HDLC + CRC-16/CCITT-FALSE（充电柜 Address=0xA0，工装 Address=0xA1）
- 桌面壳：pywebview（Edge WebView2）
- 打包：PyInstaller

## 目录结构

```
aging-test-app/
├── frontend/          # React 前端
│   ├── src/
│   └── ...
├── backend/           # Flask 后端
│   ├── app.py         # 入口
│   ├── hdlc.py        # HDLC 协议
│   ├── serial_bridge.py
│   ├── test_runner.py # 测试流程状态机
│   └── ...
├── 启动.bat           # 桌面版启动脚本
└── README.md
```

## 开发运行

后端：

```bash
cd backend
pip install -r requirements.txt
python app.py
```

前端：

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5174

## 工作模式

- Mock 模式：不依赖硬件，使用内置模拟数据，用于 UI 与流程开发
- 真实模式：连接充电柜 COM 口 + 测试工装 COM 口（115200 / 8N1），通过 HDLC 通信

未连接硬件时自动降级到 Mock 数据并明确提示。

## 测试流程

1. App 启动后分别连接充电柜和测试工装
2. 通过 0x01 命令查询柜型与槽位数
3. 设置目标完整测试次数后启动测试
4. 整柜出仓阶段：从槽位 1 到末尾逐槽发送 0x04，等待 0x02 上报最终状态
5. 间隔 3 秒后进入整柜进仓阶段：逐槽发送 0x03 给工装，工装响应后查 0x02 确认
6. 进仓完成且按键组合 + ID 判定均通过则 completed_test_count 加 1
7. 未达标槽位继续循环，全部达标后结束

## 单槽超时

- 出仓：发送 0x04 起 5 秒
- 进仓：发送 0x03 起 5 秒（含工装响应 + 充电柜 0x02 确认）

## 成功判定（AND 逻辑）

- 出仓成功：lock=0, tray=1, detect=1 且 id_ok=0
- 进仓成功：lock=0, tray=0, detect=0 且 id_ok=1 且 ID 与初始一致

## 协议命令

| 命令 | 对象 | 用途 |
|------|------|------|
| 0x01 | 充电柜 | 查询柜型与槽位数 |
| 0x02 | 充电柜 | 查询单槽状态（16 字节仓道数据块） |
| 0x03 | 测试工装 | 指定槽位进仓（响应 2 字节 result/code） |
| 0x04 | 充电柜 | 指定槽位出仓（响应 2 字节 slot_no/status） |

## 日志

```
backend/logs/
├── rounds_YYYY-MM-DD.csv     # 整轮测试
├── slots_YYYY-MM-DD.csv      # 单槽测试
├── comm_YYYY-MM-DD.log       # 通信原始报文
└── operations_YYYY-MM-DD.log # 操作日志
```

## 打包

桌面版打包为单文件 exe，使用 PyInstaller onefile + pywebview，启动后自动创建 1400×900 桌面窗口并加载本地 Flask 服务。

一键打包（Windows）：

```
双击 打包.bat
```

或手动执行：

```bash
cd frontend
npm install
npm run build          # 产出 frontend/dist

cd ../backend
pyinstaller desktop.spec --noconfirm --clean
# 产出 backend/dist/aging-test.exe
```

运行桌面版：双击 `启动.bat` 或直接执行 `backend/dist/aging-test.exe`。

> 打包前请先安装 WebView2 Runtime（Windows 10 1803+ 通常已预装）。

## 目录结构（打包后运行时）

```
aging-test-app/
├── backend/
│   ├── dist/
│   │   └── aging-test.exe    # 桌面版主程序
│   └── ...
├── 启动.bat                  # 启动桌面版
└── 打包.bat                  # 一键构建桌面版
```

运行时数据/日志写入 `aging-test.exe` 同级的 `data/` 与 `logs/` 目录。
