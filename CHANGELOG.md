# Changelog

All notable changes to this project will be documented in this file. This project follows semantic-style tags (`LTS1.0.5beta9`, etc.) and dates use ISO format.

## [1.0.5-beta9] - 2026-03-17

### Added
- 支持 **语音播报模块**（GSVmove 桥接）并开放麦克风语音识别默认开关，语音控制流程可在 AI 面板中配置。
- 新增 Vosk 语音识别（测试默认开启 `V` 热键），补齐 Push-to-Talk/状态指示。
- Ollama 模块现在可以自动探测已安装模型，缺失时会触发后台下载与提示。
- 桌宠与 UI 面板支持透明度调节，匹配桌面主题。
- 可自定义启动《鸣潮》的可执行路径。
- 与“小爱” 实时语音对话，并允许它直接打开浏览器执行指令。

### Fixed
- 尝试修复 QQ VIP 歌曲无法完整播放的问题（仍受版权限制）。
- 修复酷狗歌单获取失败的问题。
- 修复 Gemini 多模态 API 兼容问题。
- 修复自适应缩放逻辑失效的问题。
- 修复物理物体（雪豹/沙发/摩托等）的惯性计算。
- 修复控制面板右键后画面变黑的问题。

### Changed
- 闹钟命令现在统一采用 `[时,分,秒]` 调用形式。
- 内置加密密钥由于成本原因移除，粉丝可自行在群内申请专属 API KEY；加强配置信息的持久化。
- 增补 `#音响` / `#闹钟` / `#雪豹` 等对象管理器的粒子与特效联动。
- 重构大量底层代码（事件、音乐、聊天、UI、安装脚本）并完成多轮性能优化，继续推动迁移清单 Phase 8。

> Earlier changes are tracked in internal docs; future releases will continue using this Markdown changelog.
