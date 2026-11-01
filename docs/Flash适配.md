# ESP32-S3 Flash 启动适配

已验证的开发板配置为 ESP32-S3、8MB PSRAM、16MB Quad Flash，Flash ID 为 `0x207018`（manufacturer `20` / device `7018`）。

ESP32 Arduino core 3.3.12 基于 ESP-IDF 5.5.5，其原版引导程序不把这个 ID 识别为有效 XMC Flash。烧录校验虽然通过，仍会在运行应用之前循环出现 `XMC flash startup fail`。这与灯光程序或接线无关。[Espressif 的同类问题记录](https://github.com/espressif/esp-idf/issues/18947)描述了这一识别缺口。

本项目从 ESP-IDF **v5.5.5 官方源码**构建二级引导程序，仅在 `is_xmc_chip_strict(uint32_t rdid)` 开头增加：

```c
if (rdid == 0x207018) { return true; }
```

保留其他型号判断、Flash 初始化、启动镜像校验和分区检查；没有关闭启动检查，没有修改 eFuse，也没有改动全局 Arduino 库。

`scripts/setup_bootloader.py` 在项目 `.tools` 中下载官方源码、匹配的 micro-ecc 子模块及独立 Python 编译环境。源码归档校验 SHA-256：

- ESP-IDF v5.5.5：`1ac6ef6492f7a06d22e5672a346260f5eaf9ef33fd5a96e14b119d373c6c7e08`
- micro-ecc `24c60e243580c7868f4334a1ba3123481fe1aa48`：`5c7883ae2c1f8c124442a2b859ad883ba46240ad23eb474586a5038ea80c23e1`

`scripts/prepare_xmc_bootloader.py` 应用源码补丁并直接构建官方 bootloader 子项目，使用 Arduino 已安装的 Xtensa 工具链。因为链接器对中文绝对路径处理不完整，构建期间会用空闲盘符建立临时 `subst` 别名，退出时解除；真实文件仍全部位于本项目目录。调试用 ROM ELF 未安装时可能出现生成 GDB 初始化文件的警告，它不参与固件镜像构建。

重新准备和构建：

```powershell
python -X utf8 scripts\setup_bootloader.py
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

`build.ps1` 会使用 `build/bootloader-xmc207018.bin` 覆盖编译输出中的原版 bootloader，并重新生成合并固件。使用该 Flash 配置时，应通过项目脚本烧录；直接用 Arduino IDE 的普通“上传”会重新写入原版 bootloader，导致故障复现。

该补丁解决已观察到的启动识别问题，不代表这批 Flash 的所有性能/寿命参数都经过认证。已经验证启动后的协议握手和全部 8 种状态应答；断电后冷启动仍应单独检查。
