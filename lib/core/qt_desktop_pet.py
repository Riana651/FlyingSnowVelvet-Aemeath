"""桌面宠物主程序 (PyQt5版)"""
import os
import sys
import traceback


def _show_startup_error(message: str) -> None:
    """输出启动错误，并在 Windows 下弹窗提示。"""
    try:
        print(message, file=sys.stderr)
    except Exception:
        pass

    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "飞行雪绒 启动失败", 0x10)
    except Exception:
        pass


def _build_missing_dependency_message(missing_module: str, install_bat: str) -> str:
    return (
        f"缺少 Python 依赖模块：{missing_module}\n\n"
        f"请先运行：{install_bat}\n"
        "然后重新启动程序。\n\n"
        f"也可手动执行：python -m pip install {missing_module}"
    )


# 添加项目根目录到 Python 路径（向上三级，从 lib/core 到根目录）
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


if __name__ == '__main__':
    try:
        from lib.script.main import main
    except ModuleNotFoundError as e:
        missing = getattr(e, "name", None) or "unknown"
        install_bat = os.path.join(project_root, "安装依赖.bat")
        _show_startup_error(_build_missing_dependency_message(missing, install_bat))
        sys.exit(1)
    except Exception:
        _show_startup_error("程序启动失败：\n\n" + traceback.format_exc())
        sys.exit(1)

    main()
