本目录用于存放桌宠自动准备的本地辅助服务。

- `bundles/yuanbao-free-api-main.zip`：内置集成的 `chenwr727/yuanbao-free-api` 源码压缩包。
- `yuanbao-free-api/`：由 `install_deps.py` 或桌宠启动流程自动解压出来的元宝 Web 本地中转服务目录。
- 当 AI 配置启用 `YuanBao-Free-API` 且接口地址指向本地 `127.0.0.1:8000` 时，桌宠启动时会自动尝试拉起该服务。
- 首次启动成功后，会在 `logs/yuanbao_free_api_qrcode.png` 生成登录二维码图片。
- 若启动失败，请查看 `logs/yuanbao_free_api_launcher.log`。
