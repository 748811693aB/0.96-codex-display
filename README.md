# Codex MSU2 Mini 显示器

在连接到 macOS 的 160×80 `MSU2_MINI` USB 屏幕上，显示本机已登录 Codex 账号的滚动用量余额。

稳定显示模式使用固件原生绘图指令，功能包括：

- 分两行紧凑显示 5 小时窗口和一周窗口的剩余百分比，百分比数字采用更大的字体；
- 在左上角显示 51×51 的 Codex 官方图标；
- 底栏以双倍字体显示两个窗口精确到分钟的重置时刻（`5H/7D` 顺序，不显示日期）；
- 使用稍暗的配色，降低夜间观看时的刺眼感；
- 每 60 秒查询一次 Codex 用量；
- 通过轻量级像素刷新抑制固件内置的花朵动画；
- USB 断开后自动重新连接；
- 正常运行时不会擦除或写入 P25D80 Flash。

本项目使用的通信协议来自随附的 `MSU2_MINI_DemoV1.6` 上位机程序，并已对照 MSU2 开发手册验证。

## 运行要求

- macOS；
- Python 3.10 或更高版本；
- 已安装并登录 Codex CLI；
- MSU2_MINI 已连接，并显示为 `/dev/cu.usbmodem*` 设备。

本项目不需要安装第三方 Python 包。

## 启动运行

先连接 MSU2_MINI 屏幕，然后在终端中执行：

```bash
cd ~/Desktop/codex/codex-msu2-display
python3 codex_msu2_native.py
```

程序启动后会在终端打印 Codex 用量，并在屏幕上显示两个窗口的剩余百分比和重置时刻。按 `Control-C` 停止运行。

如果自动匹配不到屏幕，可以先查询设备名：

```bash
ls /dev/cu.usbmodem*
```

然后指定设备启动：

```bash
python3 codex_msu2_native.py \
  --device-glob /dev/cu.usbmodem01234567891 \
  --interval 60 \
  --draw-interval 0.2
```

参数说明：

- `--device-glob`：MSU2_MINI 的串口设备路径；
- `--interval`：Codex 用量查询间隔，单位为秒；
- `--draw-interval`：屏幕保活刷新间隔，单位为秒；
- `--codex`：可选，手动指定 Codex CLI 可执行文件的路径。

## 桌面开关按钮

桌面上的 `Codex显示开关.app` 是一键开关：

- 双击一次，安装并开启 USB 屏幕后台服务；
- 再双击一次，关闭服务并保持关闭状态；
- 每次切换后，macOS 会显示“已开启”或“已关闭”通知。

如需重建桌面按钮，请在项目目录执行：

```bash
osacompile -o ~/Desktop/Codex显示开关.app Codex显示开关.applescript
```

也可以直接在终端切换：

```bash
./toggle_codex_display.sh
```

## 登录后自动启动

自动启动配置文件中的 Python 路径、项目路径和 USB 设备名必须与本机实际情况一致。可以先执行以下命令进行确认：

```bash
which python3
pwd
ls /dev/cu.usbmodem*
```

如有差异，请先修改 `com.hanxiaobo.codex-msu2-display.plist` 中对应的值。确认无误后安装并启动 LaunchAgent：

```bash
cp com.hanxiaobo.codex-msu2-display.plist ~/Library/LaunchAgents/
launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.hanxiaobo.codex-msu2-display.plist
```

重启后台服务：

```bash
launchctl kickstart -k gui/$(id -u)/com.hanxiaobo.codex-msu2-display
```

停止并禁用后台服务：

```bash
launchctl bootout "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.hanxiaobo.codex-msu2-display.plist
```

运行日志保存在：

- `~/Library/Logs/codex-msu2-display.log`
- `~/Library/Logs/codex-msu2-display.error.log`

## 项目结构

- `codex_msu2_native.py`：稳定的原生字体仪表盘，也是推荐的启动入口；
- `codex_msu2_display.py`：Codex app-server 客户端、串口传输、RGB565 渲染器和已还原的帧缓冲协议；
- `probe_msu2_sfr.py`：读取固件的 SFR 描述符表；
- `test_msu2_glyphs.py`：原生字形和填充指令的硬件测试；
- `test_codex_msu2_display.py`：不依赖第三方包的单元测试；
- `com.hanxiaobo.codex-msu2-display.plist`：macOS LaunchAgent 自动启动配置。
- `toggle_codex_display.sh`：安装、启动、停止和卸载后台服务；
- `Codex显示开关.applescript`：桌面开关应用的源文件。

## 测试

```bash
python3 -m unittest -v
python3 -m py_compile codex_msu2_display.py codex_msu2_native.py
plutil -lint com.hanxiaobo.codex-msu2-display.plist
```

## 安全说明

正常显示时只会写入易失性的 LCD RAM 和控制器状态。项目内的仪表盘不会擦除或写入外部 P25D80 Flash。

## 许可证

MIT
