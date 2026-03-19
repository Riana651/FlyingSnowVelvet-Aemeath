飞行雪绒文档索引（LTS1.0.5pre1）

适用范围
- 本目录文档对应当前工程：飞行雪绒LTS1.0.5pre1
- 以源码为准，文档用于快速定位实现与扩展入口

项目现状速览
- 启动入口：`lib/core/qt_desktop_pet.py` -> `lib/script/main.py`
- 核心架构：PyQt5 + 事件总线（`EventCenter`）+ 动态插件发现（管理器/粒子）
- 单实例保护：Windows Mutex（`Local\\FeiXingXueRongDesktopPet_SingleInstance`）
- 命令输入：`/`（shell）、`#`（扩展命令）、无前缀（聊天）
- AI 模式：OpenAI 兼容 API / 本地 Ollama / 规则回复（见 `config/ollama_config.py`）
- 音乐系统：`netease / qq / kugou` 抽象层（默认配置当前为 `qq`）

当前 # 命令（由各模块注册）
- `#雪豹 [数量]`
- `#雪堆 [数量]`
- `#沙发 [数量]`
- `#沙发重力`
- `#摩托 [数量]`
- `#闹钟 [秒]`
- `#闹钟重力`
- `#音响 [数量]`
- `#音响重力`
- `#退出音乐登录`
- `#清理`

文档列表
- `Script开发指南.txt`
  扩展开发入口、管理器与粒子脚本规范、命令注册与清理约定。
- `事件系统使用说明.txt`
  `EventCenter` 工作机制、常用事件协议、输入/管理器通信链路。
- `调度系统使用说明.txt`
  `TimingManager` 三定时器模型、任务精度、暂停/恢复机制。
- `粒子效果说明.txt`
  当前全部已注册粒子（14个）的行为和触发点。

推荐阅读顺序
1. `Script开发指南.txt`
2. `事件系统使用说明.txt`
3. `调度系统使用说明.txt`
4. `粒子效果说明.txt`

维护约定
- 关键源码入口：
  - `lib/script/main.py`
  - `lib/core/plugin_registry.py`
  - `lib/core/event/center.py`
  - `lib/core/timing/manager.py`
  - `lib/core/qt_particle_system.py`
- 新增/修改管理器、事件协议、粒子后，同步更新本目录文档。
