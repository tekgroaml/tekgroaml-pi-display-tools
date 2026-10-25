# GitHub 发布说明

仓库：[tekgroaml/tekgroaml-pi-display-tools](https://github.com/tekgroaml/tekgroaml-pi-display-tools)。

建议Description：`Raspberry Pi HDMI configuration, fullscreen color tests, and touchscreen diagnostics.`

本地文件夹仍叫`pi-setting`；远程仓库名称为`tekgroaml-pi-display-tools`。`/opt/pi-setting`、`/etc/pi-setting`、`/var/lib/pi-setting`和`pi_setting`是程序接口，不应仅为仓库改名而替换。程序会从当前登录用户及本机设备探测身份和USB路径，不预装某台样机的配置。

## 已处理

- 安装文档不再使用开发者Mac路径和固定树莓派用户名。
- 触摸示例使用`eventN`/`eventM`与`YOUR_DESKTOP_USER`，实际USB路径在目标机确认后生成。
- 测试EDID改为合成身份；旧配置迁移识别不再硬编码某块显示器的完整哈希。
- 移除Python字节码缓存，防止其中记录编译时的个人路径；增加本机配置、日志和私有文件的忽略规则。
- 文档保留可复核的测试平台及历史验证限制，移除“当前机器已配置”的陈述。

## 发布元数据与维护

1. GitHub账号/组织为`tekgroaml`，安装文档已配置真实HTTPS clone地址。
2. 配套客户FAQ：[tekgroaml-display-support](https://github.com/tekgroaml/tekgroaml-display-support)；文档不依赖电脑相邻目录。
3. 仓库目前未选择授权许可证。所有者应决定代码许可，再添加对应`LICENSE`；不要把“仓库公开可读”当成已明确给予复用许可。
4. 重新核对兼容性范围。现有测试不代表Pi 5、所有操作系统、冷启动或多指并发都已验证。

维护仓库时保留真实下载链接与适用范围。个人登录凭据不写入仓库。首次内容提交保留远程初始化README的历史。

## 本次检查结果（2026-10-25）

- 31个项目文件通过文本/源代码检查，25项逻辑测试通过。
- 所有Python源文件语法及Shell安装/卸载脚本语法通过。
- 8处仓库内文档链接存在，独立复制目录后仍可解析，不依赖相邻FAQ目录。
- 未发现检查范围内的个人主目录、真实测试主机IP、已知测试密码、私钥或GitHub访问令牌；字节码缓存已移除。
- `/opt`、`/etc`、`/var/lib`、`/run`、`/sys`、`/dev`等程序所需Linux路径保留。用户身份、EDID身份和USB路径在目标机运行时生成。

这些是发布内容检查及逻辑测试，不等同于重新验证所有实体屏幕或冷启动行为。本次未改动树莓派上的已运行安装版本。

## 检查命令

在项目根目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
bash -n scripts/install.sh
bash -n scripts/uninstall.sh
git status --short
```

提交前查看待上传清单，避免把运行生成的配置、日志、设备备份或私钥加入版本库。

## 版本发布维护

应用版本与兼容声明以`VERSION.json`为唯一来源，发布改动按[版本规范](docs/05-版本与升级.md)升号并更新CHANGELOG。安装包指纹包含文档，不能在同一已发布版本号下修改代码或随包文档。Git标签使用`vX.Y.Z`并指向对应提交；不移动已公开标签。不要将本机生成的`installation.json`、配置、日志或备份加入仓库。

2.2.0新增`ltm-420x960-60`候选兼容档：触摸/非触摸样机报告同样EDID但实物结果不同，故强制要求用户显式核对产品限制。EDID匹配不能作为真实产品型号认证。发布说明必须同时保留失败变体及尚未验证的冷启动流程，不标为通用“6.2英寸屏闪烁修复”。
