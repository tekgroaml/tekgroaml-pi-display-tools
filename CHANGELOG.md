# Changelog

## 2.0.0 — 2026-10-25

Unified public numbering with Linux connectors:

| Number | Configuration | Test | Linux connector | Board label |
| --- | --- | --- | --- | --- |
| 1 | `--port 1` | `--screen 1` | `HDMI-A-1` | HDMI0, next to USB-C power |
| 2 | `--port 2` | `--screen 2` | `HDMI-A-2` | HDMI1 |

**Breaking change:** `screen-config --port` previously used board numbers 0/1; it now accepts only 1/2. Update old scripts: old `--port 0` becomes `--port 1`, and old `--port 1` becomes `--port 2`. `screen-test --screen 1/2` and touch-map `--screen1-device` / `--screen2-device` keep their existing meanings.

Public numbers change only at the configuration command boundary. Existing saved configuration keys, USB-path mappings and the board's physical 0/1 labels retain their original meanings; no manual JSON renumbering is required.

中文：配置和测试命令统一按Linux接口编号1、2。更新旧脚本中的`--port`参数；已保存配置无需手工改号。测试窗口的SCREEN 1/2标签保持原意。Linux的`HDMI-A-1/2`与板子印刷的HDMI0/1只是两套原生标号，并不矛盾。
