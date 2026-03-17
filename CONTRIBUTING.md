# Contributing Guide

感谢你愿意为 **飞行雪绒 LTS** 提供帮助！本仓库目前仍在 LTS1.0.5 beta 迁移期，代码改动需要兼顾运行时稳定性与文档同步。请遵循以下约定：

> 许可说明：所有源码贡献将以 [Apache License 2.0](LICENSE-CODE) 授权，并自动附带相应的专利许可。`resc/` 等资源文件受 [LICENSE-ASSETS](LICENSE-ASSETS) 约束，如需替换/新增素材，请确认你拥有其分发权或已获授权。

## 1. 基础要求

- 目标平台：Windows 10/11，Python 3.7–3.13（推荐 3.10+）。
- 所有提交必须保持 UTF-8 / ASCII 源码（除非原文件已有其它编码）。
- 任何新增/修改模块都需要对应的清理逻辑（事件 `unsubscribe`、任务回收、资源释放）。
- 避免引入未记录的第三方依赖；如确有需要，请同时更新 `requirements.txt` 与 `install_deps.py::DEPENDENCIES`。
- 请勿提交个人密钥 / 账号信息；`config/ollama_config.py` 会优先读取环境变量，仓内默认留空。

## 2. 开发环境

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m compileall config lib install_deps.py scripts
```

- 桌宠入口：`python/we pythonw lib/core/qt_desktop_pet.py`；
- 文档门户：`python scripts/generate_doc_portal.py`；
- 打包检查：`python scripts/package_release.py --dry-run`。

## 3. 代码规范

1. **模块拆分**：优先复用 `lib/core` 中的 helper，减少重复样板；同一功能请集中在专用模块（参考 `doc/迁移清单任务.txt` 的 Phase 指南）。
2. **事件 & 命令**：所有订阅都需在 `cleanup()` 中退订；跨模块通信首选事件（`EventType.*`）。
3. **UI**：新组件放在 `lib/script/ui/`，遵循现有模式（动画在 `_particle_helper`，提示在 `tooltip_panel`）；多次复用的按钮/容器请抽出 helper。
4. **配置**：公共入口使用 `config/config.py` 提供的 facade；新增配置项需在对应 `config/config_*` 与运行代码中同步。
5. **文档**：新增/修改管理器、粒子、事件协议时，必须更新 `doc/*.txt` 对应章节。

## 4. 测试与自检

在提交 PR 之前请完成：

- `python -m compileall config lib install_deps.py scripts`
- `python scripts/package_release.py --dry-run`（确认清单输出）
- 手动运行桌宠一次，确认启动、命令框、音乐、AI、语音核心路径不回归
- 若修改了 `doc/`、贡献/赞助清单或生成脚本，请重新执行 `python scripts/generate_doc_portal.py`

推荐附带说明你验证过的场景（AI 模式、音乐平台、语音识别、工具调度等）。

## 5. 提交信息 / PR 模板

请尽量保持以下结构：

- `feat: ......` / `fix: ......` / `docs: ......` / `chore: ......`
- 描述影响范围（例：`feat: add qq music provider cache fallback`）
- 如果涉及迁移步骤，请在 `doc/迁移清单任务.txt` 中同步勾选/修改状态
- 更新 `CHANGELOG.md`（新增版本段落或补充当前版本）

## 6. Issue 指南

提交 Issue 时请包含：

- Windows 版本、Python 版本、是否使用安装脚本
- 使用的 AI 模式（OpenAI 兼容 API / Ollama / 规则回复）
- 是否启用语音 / GSVmove
- 重现步骤、对应日志（`logs/app_*.log`）或截图

---

欢迎在 PR 中附上录屏 / gif / 截图，帮助快速复现与验证。感谢你的贡献！
