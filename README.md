# TEKGROAML Pi Display Tools

Display configuration, full-screen color tests, touch targets and tap-to-change colors for Raspberry Pi. Tested platform: Raspberry Pi 4 Model B, Raspberry Pi OS Bookworm Desktop 64-bit, labwc/Wayland. Other platforms are not validated.

GitHub仓库：[tekgroaml-pi-display-tools](https://github.com/tekgroaml/tekgroaml-pi-display-tools)。树莓派双HDMI配置、全屏颜色与触摸测试工具。内部Python包、命令和Linux安装路径继续使用`pi-setting`，无须与仓库名一致。

## Install / 安装

Download or clone this repository, open its root directory **on the Raspberry Pi**, then run:

```bash
sudo bash scripts/install.sh
```

Keep the graphical desktop logged in. Connect HDMI for video and a USB data cable for touch. Run test commands as the desktop user, not with sudo. The installer is limited to the tested Pi 4 / Bookworm 64-bit platform.

## Version and upgrades / 版本与升级

```bash
pi-setting version
pi-setting check-update --source ~/pi-setting
sudo pi-setting upgrade --source ~/pi-setting
```

Checks compare the installed application with an already downloaded release; no network lookup or download is performed. Version 2.1 introduces this manager. To bootstrap an older installation, run the new release's `scripts/install.sh`. Same versions are skipped; use `--reinstall` for an explicit repair. Major upgrades require `--allow-major`, downgrades are rejected. See the [version guide](docs/05-版本与升级.md).

## Documentation / 文档

先读文档，再安装：

1. [命令说明](docs/01-命令说明.md)
2. [上传安装与使用](docs/02-上传安装与使用.md)
3. [验证记录](docs/03-验证记录.md)
4. [触摸测试与双屏映射](docs/04-触摸测试与双屏映射.md)
5. [版本管理与升级](docs/05-版本与升级.md)

```bash
sudo bash scripts/install.sh
screen-config list
screen-config set --port 2 --mode 800x800@60 --save
screen-test pattern
screen-test touch
screen-test tap-cycle
screen-test cycle --interval 5
screen-test stop
```

**统一编号1、2：** `--port 1` / `--screen 1` → `HDMI-A-1`（板子HDMI0）；`--port 2` / `--screen 2` → `HDMI-A-2`（板子HDMI1）。旧版`--port 0/1`需要更新，已保存配置保持兼容。See the [2.0 breaking change](CHANGELOG.md).

程序不修改屏幕固件。显示参数保存在树莓派系统，颜色测试为桌面上的 layer-shell 全屏覆盖层。

For optional mapping of two identical-name touch controllers, see the touch guide. USB-to-screen pairing must be confirmed on each host; no developer machine mapping is supplied.

发布者请阅读[GitHub发布说明](PUBLISHING.md)。下载者无需使用开发者的账号、IP、绝对路径或USB插口编号。Customer troubleshooting: [TEKGROAML Display Support](https://github.com/tekgroaml/tekgroaml-display-support).
