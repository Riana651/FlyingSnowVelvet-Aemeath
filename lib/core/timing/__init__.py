# Timing module
_timing_manager = None


def get_timing_manager():
    """获取全局 TimingManager 实例（由 PetWindow 创建后注册）"""
    return _timing_manager


def register_timing_manager(manager):
    """注册全局 TimingManager 实例（仅由 PetWindow 调用一次）"""
    global _timing_manager
    _timing_manager = manager
