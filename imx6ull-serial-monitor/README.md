# i.MX6ULL ALPHA：USB 串口设备状态监测终端

目标硬件：正点原子 ALPHA 底板 + eMMC 核心板；电脑：Windows 11。

**电脑里的 VirtualBox/WSL Linux 是开发环境，开发板上的 Linux 是运行环境。两者不是同一个系统。** 本项目通过板载 CH340（USB_TTL → UART1 `/dev/ttymxc0`）通信，不需要网线。

项目包含可运行的 PC 模拟模式、Win11 桌面界面/命令行、ARM Linux C 应用、AP3216C/ICM20608 内核驱动源码、设备树片段、上传/安装脚本、协议测试和中文文档。实物尚未连接验证；测试证据及限制见 `docs/06_测试报告.md`。不要把 PC 模拟数据当作真实传感器数据。

## 从哪里开始

1. 双击 `scripts/start-demo.cmd`：电脑上模拟通信，无需开发板。
2. 双击 `scripts/start-dashboard.cmd`：选择“模拟模式”后连接，查看数据、修改阈值、消音。
3. 阅读 `docs/01_首次连接与运行.md`：先找到真实 CH340 串口并看到开发板启动日志。
4. 阅读 `docs/04_烧录与部署.md`：已有 Linux 优先部署应用；系统无法启动时再按板卡版本恢复 eMMC 固件。
5. 先在板上运行 `--mock` 验证真实 USB 串口，再接入 `drivers/` 里的传感器驱动。

Windows 需要 Python 3.10+（桌面版需 tkinter）。已随项目附带 pyserial 3.5 和其许可证，串口功能不要求联网安装依赖。可用 `py -3 --version` 检查；若没有 `py`，使用已安装的 `python.exe` 完整路径。命令中的 `COM7` 是示例，必须替换为实际 CH340 端口。

```powershell
cd 'D:\linux项目\imx6ull-serial-monitor'
py -3 host\monitor.py --simulate --seconds 12
py -3 host\monitor.py --list
py -3 host\dashboard.py
```

## 功能边界

- 采集 AP3216C 光照原始值、ICM20608 六轴原始值，周期 200～10000 ms。
- 用相邻采样的最大轴差值判断运动，用光照原始值判断明暗变化；这是低速演示算法，不是专业振动频谱分析或可靠门禁判定。
- LED/蜂鸣器报警，KEY0 或 PC 消音；条件恢复正常后重新布防。
- 串口帧有版本、类型、序号、长度、CRC16；解析器有 256 字节载荷上限及残帧超时。
- 阈值持久化；告警以单独文件持久化，PC SQLite 提交后确认，板端再删除，重复事件去重。
- 32 个内存事件、128 个磁盘事件的上限；满时丢弃新事件并增加错误计数。实时曲线只保留最新样本，不补传历史全量采样。
- PC 保存 CSV、告警 SQLite。CSV 每 10 MiB 分卷；总日志容量需用户定期归档。
- 断开 PC 后板端继续运行；PC 重新连接握手后补传告警。GUI 需手动重连，未实现自动 COM 端口重发现。

## 目录

```text
board/           ARM Linux 用户态 C 程序（采样线程 + 串口/存储线程）
common/          C 串口帧编解码
drivers/         原创 I2C/SPI misc 字符驱动、DTS 片段（针对 4.1.15 API）
host/            Win11 CLI、Tk 桌面界面、模拟器、串口上传工具
host/vendor/     pyserial 3.5，保留原许可证
scripts/         构建、部署、临时串口会话、电脑/板端检查
tests/           Python 与 C 协议交叉验证、上位机测试、Linux PTY 集成测试
release/         ARM 应用和部署包（以测试报告列出的实际产物为准）
docs/            设计、协议、烧录、调试、面试知识点、验证报告
logs/            PC 运行时生成的 CSV 与 SQLite
```

## 学习顺序

先读 `common/protocol.c` / `host/protocol.py`，理解一串字节怎样变成消息。
再读 `board/src/main.c`，理解线程、互斥锁、有界队列、状态和错误处理。
然后读 `serial.c`、`storage.c`、`sensors.c`，最后看 `drivers/mon_sensors.c`。

指南对应：第 40～45 章字符设备/设备树，第 47～52 章并发/中断/IO，第 54～58 章设备模型与标准子系统，第 61～62 章 I2C/SPI，第 74～75 章 Regmap/IIO，第 B3～B4 章调试。项目的串口协议、用户态多线程、断线补传属于在教程基础上的扩展。

## 串口不能同时给两个程序使用

上传工具已更新为v2：逐块接收确认，SHA256成功才替换部署包。此前用户实物出现v1长heredoc接收不完整，原因和重试方法见`docs/09_串口上传故障与v2修复.md`。新增7项测试通过，合计21项；v2实物重试待完成。

调试工具 SecureCRT/PuTTY、PC 监测程序、VirtualBox USB 直通只能按当前步骤选择一个拥有 CH340。板端 login shell、getty、内核 printk 和业务协议也不能无条件共用 UART。先使用临时会话脚本；它默认 300 秒自动退出并恢复终端，不修改启动环境或 `/etc/inittab`。

## 许可证与来源

新增应用/脚本/文档采用 MIT（`LICENSE`）；`drivers/mon_sensors.c` 为 GPL-2.0-only。pyserial 保留其 BSD 许可证。未复制厂商整套 BSP、PDF 或 MfgTool 镜像；它们继续使用原资料目录与许可证，位置见 `docs/07_本机资料索引.md`。预编译应用链接的 C 运行库信息与对应源码获取方式见 `THIRD_PARTY.md`。
