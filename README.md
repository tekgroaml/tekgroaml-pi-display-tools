# TEKGROAML Pi Display Tools

Display configuration, full-screen color tests, touch targets and tap-to-change colors for Raspberry Pi. Tested platform: Raspberry Pi 4 Model B, Raspberry Pi OS Bookworm Desktop 64-bit, labwc/Wayland. Other platforms are not validated.

GitHub仓库：[tekgroaml-pi-display-tools](https://github.com/tekgroaml/tekgroaml-pi-display-tools)。树莓派双HDMI配置、全屏颜色与触摸测试工具。内部Python包、命令和Linux安装路径继续使用`pi-setting`，无须与仓库名一致。

## Install / 安装

Download or clone this repository, open its root directory **on the Raspberry Pi**, then run:

```bash
sudo bash scripts/install.sh
```

Keep the graphical desktop logged in. Connect HDMI for video and a USB data cable for touch. Run test commands as the desktop user, not with sudo. The installer is limited to the tested Pi 4 / Bookworm 64-bit platform.

## Documentation / 文档

先读文档，再安装：

1. [命令说明](docs/01-命令说明.md)
2. [上传安装与使用](docs/02-上传安装与使用.md)
3. [验证记录](docs/03-验证记录.md)
4. [触摸测试与双屏映射](docs/04-触摸测试与双屏映射.md)

```bash
sudo bash scripts/install.sh
screen-config list
screen-config set --port 1 --mode 800x800@60 --save
screen-test pattern
screen-test touch
screen-test tap-cycle
screen-test cycle --interval 5
screen-test stop
```

`--port 0` / `--screen 1` 对应 HDMI0；`--port 1` / `--screen 2` 对应 HDMI1。

程序不修改屏幕固件。显示参数保存在树莓派系统，颜色测试为桌面上的 layer-shell 全屏覆盖层。

For optional mapping of two identical-name touch controllers, see the touch guide. USB-to-screen pairing must be confirmed on each host; no developer machine mapping is supplied.

发布者请阅读[GitHub发布说明](PUBLISHING.md)。下载者无需使用开发者的账号、IP、绝对路径或USB插口编号。Customer troubleshooting: [TEKGROAML Display Support](https://github.com/tekgroaml/tekgroaml-display-support).
