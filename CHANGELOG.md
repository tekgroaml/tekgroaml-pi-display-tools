# Changelog

## 2.3.1

- Generate persistent USB-TOUCH-1/2 device links from explicitly confirmed HDMI/touch pairs. Reconfiguration updates links when pairs are exchanged; uninstall removes labels.
- Document fixed cable pairs and reversed touch mapping; USB port numbers never imply HDMI numbers.

## 2.3.0 — 2026-10-25

- Name repair profiles and convenience `.sh` entry points by size, resolution, nominal refresh and reported driver label.
- Add customer-facing device names, original driver/timing data, repaired timing data, issue summaries and validation limits to the profile registry.
- Add `screen-config profiles --json` and human-readable device cards.
- Preserve `lontium-720` and `ltm-420x960-60` as aliases, including existing saved boot profiles and explicit acknowledgment requirements. New saves use canonical names.
- Keep EDID matching and timing corrections unchanged. Customer labels and script IDs do not identify a physical panel or distinguish devices reporting identical EDID.
- Add consistent product cards, a naming policy and a template in the support repository; list the unresolved non-touch variant separately without a repair script.

## 2.2.0 — 2026-10-25

- Add the guarded `ltm-420x960-60` profile: keep the known 420x960 timing and change pixel clock from 28MHz to 32.4MHz for 60Hz.
- Require `--confirm-profile` because touch and unresolved non-touch samples report identical EDID data; matching does not identify the physical product variant.
- Validate known controller, descriptors and timing; preserve extension blocks, per-unit identity and existing 720-profile behavior.
- Support explicit saved acknowledgment and identity-bound boot restoration, manual reset via `auto --save`, and prior-override restoration when mode selection fails.
- Acknowledge identical manually tested overrides only after explicit confirmation; do not take ownership of unrelated overrides.
- Add Chinese/English product instructions in the support repository. The non-touch sample was not fixed; new CLI cold-start behavior still requires hardware validation.

## 2.1.0 — 2026-10-25

- Add a single `VERSION.json` release manifest for application, command and configuration versions.
- Add `pi-setting version`, `check-update --source` and `upgrade --source`, plus `--version` on existing commands.
- Compare numeric versions, skip unchanged releases, reject downgrades, require `--allow-major` for major upgrades, and validate configuration formats before installation.
- Record installed version/content fingerprint and backups; stage application updates and restore previous application/configuration on installation failure.
- Preserve supported existing settings, touch service state and test modes; test counters restart after an update.
- No new configuration format: display, touch and runtime formats remain 1; command numbering stays 1/2.
- Update checks compare a previously downloaded directory. They do not automatically query GitHub or download updates.

## 2.0.0 — 2026-10-25

Unified public numbering with Linux connectors:

| Number | Configuration | Test | Linux connector | Board label |
| --- | --- | --- | --- | --- |
| 1 | `--port 1` | `--screen 1` | `HDMI-A-1` | HDMI0, next to USB-C power |
| 2 | `--port 2` | `--screen 2` | `HDMI-A-2` | HDMI1 |

**Breaking change:** `screen-config --port` previously used board numbers 0/1; it now accepts only 1/2. Update old scripts: old `--port 0` becomes `--port 1`, and old `--port 1` becomes `--port 2`. `screen-test --screen 1/2` and touch-map `--screen1-device` / `--screen2-device` keep their existing meanings.

Public numbers change only at the configuration command boundary. Existing saved configuration keys, USB-path mappings and the board's physical 0/1 labels retain their original meanings; no manual JSON renumbering is required.

中文：配置和测试命令统一按Linux接口编号1、2。更新旧脚本中的`--port`参数；已保存配置无需手工改号。测试窗口的SCREEN 1/2标签保持原意。Linux的`HDMI-A-1/2`与板子印刷的HDMI0/1只是两套原生标号，并不矛盾。
