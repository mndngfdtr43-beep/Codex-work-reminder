# Codex工作提醒

让 ESP32-S3 开发板上的 RGB 灯显示 Codex 桌面版当前会话的工作状态，并通过 BOOT 按钮停止、继续或发送任务。

支持 Windows 上的 Codex 桌面版，自动跟随当前打开的会话，包括新建会话。切换聊天无需重启监测程序。

## 功能

- 板载 RGB 灯显示工作中、已停止、空闲、等待确认及连接状态。
- 工作中短按 BOOT：停止当前一轮；确认停止后，再按 BOOT 继续。
- 空闲或新建会话：在输入框写好任务，按 BOOT 发送。
- 每个会话分别记录暂停状态；只控制当前前台的 Codex 会话。
- 支持后台运行、串口重连、按键消抖和重复事件过滤。
- 不需要 API 密钥。电脑通过 Windows UI Automation 读取界面，通过 USB 串口连接开发板。

## 硬件与环境

| 项目 | 要求 |
|---|---|
| 开发板 | ESP32-S3 DevKitC-1 N16R8 |
| 灯光 | 板载 RGB LED，默认 GPIO48，部分板卡为 GPIO38 |
| 按键 | 板载 BOOT / GPIO0 |
| 连接 | USB 数据线连接开发板 USB 转串口接口 |
| 系统 | Windows，Codex 桌面版 |
| 软件 | Python 3.10+，Arduino IDE 或 arduino-cli |
| 已验证依赖 | ESP32 core 3.3.12、Adafruit NeoPixel 1.15.2 |

只需连接 USB 数据线。电源指示灯不受程序控制。短按并松开 BOOT（约 0.1～1 秒）；上电或复位时按住 BOOT 会进入下载模式。

## 安装和烧录

下载项目后，在项目根目录打开 PowerShell。安装 Python，并在 Arduino 开发板管理器安装 `esp32 by Espressif Systems` **3.3.12**。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
.\.venv\Scripts\python.exe -X utf8 -m bridge --list-ports
```

确认目标开发板串口后烧录。以下 `COM3` 仅为示例，请换成实际端口。烧录将覆盖指定开发板的现有程序。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -Upload -Port COM3
```

脚本先查找 PATH 中的 arduino-cli，再检查 Arduino IDE 的常用安装位置。自定义安装时，使用 `-ArduinoCli` 参数指定可执行文件。

首次构建会下载依赖并建立项目内的独立编译环境。已验证的 Flash ID `0x207018` 需要适配引导程序，构建脚本会自动准备并使用它。**请使用项目脚本烧录**，详见 [Flash 适配](docs/Flash适配.md)。

如果通信正常但 RGB 灯不亮，请核对板卡版本；GPIO38 版本使用：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -Upload -Port COM3 -OnboardPin 38
```

## 使用

1. 双击 `灯光测试.cmd`。初始蓝色常亮；短按 BOOT 切换颜色，此模式不操作 Codex。
2. 退出灯光测试，打开 Codex 桌面版。
3. 双击 `后台启动监测.cmd`，或运行保留终端窗口的 `启动监测.cmd`。
4. 将要控制的 Codex 会话放到前台。切换已有聊天或打开新会话后，程序自动跟随。
5. 退出后台监测用 `停止监测.cmd`；普通终端用 Ctrl+C 退出。

只有一个候选串口时可自动选择；多个设备时显式指定：

```powershell
.\start.cmd --port COM3
.\.venv\Scripts\python.exe -X utf8 scripts\monitor.py start --port COM3
```

两种启动方式不要同时运行。Arduino 串口监视器也不能同时占用开发板串口。

## 灯光和按键

| 灯光 | 含义 | BOOT 行为 |
|---|---|---|
| 绿色常亮 | 当前会话工作中 | 请求停止 |
| 黄色常亮 | 已由程序停止 | 输入框为空时发送继续指令 |
| 蓝色低亮常亮 | 空闲或本轮结束 | 有草稿时发送；空白时不操作 |
| 黄色闪烁 | 等待电脑端确认 | 不代替批准 |
| 白色快闪 | 等待操作结果 | 等待界面确认 |
| 红色闪烁 | 操作失败或被保护条件拒绝 | 查看运行日志 |
| 紫色闪烁 | 页面加载、最小化或无法识别 | 恢复可识别的 Codex 页面 |
| 蓝色慢闪 | 电脑心跳中断 | 检查 USB 和监测程序 |

暂停是停止当前一轮，再在同一会话发送“继续完成当前任务中尚未完成的工作；已完成的操作不要重复执行。”已发生的修改不会回滚，独立后台进程可能继续运行。

有草稿时优先发送用户草稿；不会覆盖为继续指令。已完成且输入框为空的任务不会自动重做。

## 会话识别与边界

灯光表示当前查看的会话，不是所有后台会话的汇总。多个 Codex 窗口时优先跟随前台窗口；切到其他软件后仍可显示上次查看的会话，但 BOOT 不控制后台窗口。

暂停记忆保存在监测进程内，最多保留最近 256 个会话。程序使用界面中聊天列表项的标识区分会话，并在操作前再次检查输入框所属页面。侧栏重建、聊天改名、无法区分的同名项或缺失列表项可能导致暂停记忆丢失；此时在目标会话输入“继续”，再按 BOOT 发送即可。

Codex 界面更新可能改变可访问控件，需要调整适配器。等待确认状态只覆盖可识别的批准和提交答案控件。发送后页面刷新时可能短暂紫闪，随后自动恢复。

## 验证与诊断

```powershell
# 只读检查当前 Codex 页面
.\.venv\Scripts\python.exe -X utf8 -m bridge --inspect

# 检查开发板通信（先停止监测程序以释放串口）
.\.venv\Scripts\python.exe -X utf8 scripts\verify_board.py --port COM3 --expect-led-pin 48 --expect-led-count 1

# 软件测试
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

后台日志位于项目内 `.local/monitor.log`，可能包含会话标题，仅保留在本地，已由 `.gitignore` 排除；分享诊断日志前请检查个人信息。

验证范围见 [验证记录](docs/验证记录.md)。
