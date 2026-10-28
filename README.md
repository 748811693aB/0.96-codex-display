# Codex + DeepSeek MSU2 Mini 显示器

在连接到 macOS 的 160×80 `MSU2_MINI` USB 屏幕上轮流显示：

- **Codex 页面**：5 小时窗口和一周窗口的剩余百分比，底栏显示两个窗口的重置时刻；
- **DeepSeek 页面**：账户剩余总余额（充值余额 + 赠送余额）、充值余额和赠送余额明细；
- DeepSeek 页面还显示默认 `deepseek-flash` 输出价格当前处于 `PEAK`/`VAL`（波峰/波谷）以及相对峰谷均价的倍数；倍率位于鲸鱼图标下方，鲸鱼和倍率会按价格从绿→蓝→红渐变，GFT 金额缩小并固定在右下角。可用 `--deepseek-price-model` 切换模型。
- 两个页面默认每 **30 秒**切换一次，左侧图标也随之切换为 Codex 花朵或 DeepSeek 鲸鱼。

稳定显示模式使用固件原生绘图指令，功能包括：

- 分两行紧凑显示 Codex 的剩余百分比，百分比数字采用更大的字体；
- 左侧 51×51 的 Codex 官方图标，切换到 DeepSeek 页面时换成 58×43 的 DeepSeek 鲸鱼图标；
- DeepSeek 页面以最大字号显示总余额，第二行显示充值余额，底栏显示赠送余额；
- 底栏以双倍字体显示 Codex 两个窗口的重置时刻（格式为 `HH:MM/MM-DD`）；
- 使用稍暗的配色，降低夜间观看时的刺眼感；
- 每 60 秒查询一次 Codex 用量，每 5 分钟查询一次 DeepSeek 余额和 API 价格状态；
- 通过轻量级像素刷新抑制固件内置的花朵动画；
- USB 断开后自动重新连接；
- 正常运行时不会擦除或写入 P25D80 Flash。

本项目使用的通信协议来自随附的 `MSU2_MINI_DemoV1.6` 上位机程序，并已对照 MSU2 开发手册验证。

## 运行要求

- macOS；
- Python 3.10 或更高版本；
- 已安装并登录 Codex CLI；
- 已连接 MSU2_MINI，并显示为 `/dev/cu.usbmodem*` 设备；
- 至少一种 DeepSeek 凭证（见下一节）。

本项目不需要安装第三方 Python 包。

## DeepSeek 余额凭证

程序按以下优先级自动查找凭证：

1. 命令行参数 `--deepseek-key`；
2. 环境变量 `DEEPSEEK_API_KEY`（DeepSeek 开放平台的 `sk-` 密钥）；
3. 命令行参数 `--deepseek-key-file` 指定的文件；
4. 以下文件中第一个非空、非注释行：
   - `~/.config/deepseek-display/api_key`
   - `~/.config/deepseek/api_key`
   - `~/.deepseek/api_key`
   - 项目目录下的 `.deepseek_api_key`
5. **DeepSeek Harness 的登录凭证**（`~/.dsh/.credentials.yaml`），无需额外配置。

使用 API Key 时读取 `https://api.deepseek.com/user/balance`；使用 Harness 登录凭证时读取
`https://platform.deepseek.com` 的钱包汇总接口，与桌面端显示的是同一份余额数据。

凭证失效时，DeepSeek 页面显示 `ERROR` / `RETRYING`，程序会每小时重试一次，并在日志中提示重新登录或配置 API Key。凭证本身不会写入任何日志。

## 启动运行

先连接 MSU2_MINI 屏幕，然后在终端中执行：

```bash
cd ~/Desktop/codex/codex-msu2-display
python3 codex_msu2_native.py
```

程序启动后会在终端打印 Codex 用量和 DeepSeek 余额，并在两块页面之间自动轮换。按 `Control-C` 停止运行。

如果自动匹配不到屏幕，可以先查询设备名：

```bash
ls /dev/cu.usbmodem*
```

然后指定设备启动：

```bash
python3 codex_msu2_native.py \
  --device-glob /dev/cu.usbmodem01234567891 \
  --rotate-interval 30 \
  --interval 60 \
  --deepseek-interval 300
```

参数说明：

- `--device-glob`：MSU2_MINI 的串口设备路径；
- `--rotate-interval`：两个页面的切换间隔，单位为秒，默认 30；设为 0 可关闭轮换；
- `--interval`：Codex 用量查询间隔，单位为秒，默认 60；
- `--deepseek-interval`：DeepSeek 余额查询间隔，单位为秒，默认 300；
- `--page`：`auto`（默认，轮换）、`codex` 或 `deepseek`，用于固定显示其中一页；
- `--draw-interval`：屏幕保活刷新间隔，单位为秒；
- `--codex`：可选，手动指定 Codex CLI 可执行文件的路径；
- `--deepseek-key` / `--deepseek-key-file` / `--dsh-credentials`：手动指定 DeepSeek 凭证；
- `--deepseek-price-model`：峰谷价显示所用的模型，默认 `deepseek-flash`，也支持 `deepseek-v4-pro`；价格表来自 DeepSeek 官方文档。
- `--preview-dir`：把两个页面渲染成 PNG 预览后退出；
- `--demo`：使用示例数据渲染，不联网也不需要设备；
- `--once`：只绘制一帧后退出。

## 预览页面

不需要连接屏幕，也不需要联网即可查看两个页面的效果：

```bash
python3 codex_msu2_native.py --demo --preview-dir preview
```

会在 `preview/` 下生成 `codex.png` 和 `deepseek.png`。

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

- `codex_msu2_native.py`：双页面仪表盘和轮换调度，也是推荐的启动入口；
- `deepseek_balance.py`：DeepSeek 余额查询、凭证发现和金额格式化；
- `codex_msu2_display.py`：Codex app-server 客户端、串口传输、RGB565 渲染器和已还原的帧缓冲协议；
- `probe_msu2_sfr.py`：读取固件的 SFR 描述符表；
- `test_msu2_glyphs.py`：原生字形和填充指令的硬件测试；
- `test_codex_msu2_display.py`：不依赖第三方包的单元测试；
- `com.hanxiaobo.codex-msu2-display.plist`：macOS LaunchAgent 自动启动配置；
- `toggle_codex_display.sh`：安装、启动、停止和卸载后台服务；
- `Codex显示开关.applescript`：桌面开关应用的源文件。

## 测试

```bash
python3 -m unittest -v
python3 -m py_compile codex_msu2_display.py codex_msu2_native.py deepseek_balance.py
plutil -lint com.hanxiaobo.codex-msu2-display.plist
```

## 安全说明

正常显示时只会写入易失性的 LCD RAM 和控制器状态。项目内的仪表盘不会擦除或写入外部 P25D80 Flash。DeepSeek 凭证只在本机读取，用于请求官方余额接口，不会输出到终端或日志。

## 许可证

MIT
