"""
移动控制器模块 - 管理实体的移动逻辑

将移动相关的状态和算法从 PetWindow 中抽离，形成独立的移动控制器。
支持速度插值、方向翻转、目标追踪等功能。
"""

from typing import Optional, Callable
from PyQt5.QtCore import QPoint

from config.config import BEHAVIOR


class MovementController:
    """
    移动控制器 - 管理实体的移动状态和算法
    
    职责：
    - 管理移动状态（是否正在移动、目标位置、当前速度）
    - 实现速度插值算法（加速、减速）
    - 处理方向翻转
    - 计算每帧的位移
    
    不负责：
    - 实际的窗口移动（由调用者执行）
    - 状态机的状态切换（由调用者通过回调触发）
    """

    def __init__(self,
                 on_position_update: Optional[Callable[[QPoint], None]] = None,
                 on_move_complete: Optional[Callable[[], None]] = None,
                 on_direction_change: Optional[Callable[[bool], None]] = None):
        """
        初始化移动控制器
        
        Args:
            on_position_update: 位置更新回调，参数为新位置
            on_move_complete: 移动完成回调
            on_direction_change: 方向改变回调，参数为是否翻转
        """
        # 移动状态
        self._moving = False
        self._target = QPoint(0, 0)
        self._current_speed = BEHAVIOR['move_min_speed']
        
        # 方向
        self._flipped = False
        
        # 回调
        self._on_position_update = on_position_update
        self._on_move_complete = on_move_complete
        self._on_direction_change = on_direction_change

    # ==================================================================
    # 属性访问器
    # ==================================================================

    @property
    def is_moving(self) -> bool:
        """是否正在移动"""
        return self._moving

    @property
    def target(self) -> QPoint:
        """当前目标位置"""
        return self._target

    @property
    def flipped(self) -> bool:
        """当前朝向（是否翻转）"""
        return self._flipped

    @flipped.setter
    def flipped(self, value: bool):
        """设置朝向"""
        if self._flipped != value:
            self._flipped = value
            if self._on_direction_change:
                self._on_direction_change(value)

    # ==================================================================
    # 移动控制
    # ==================================================================

    def start_move(self, target: QPoint) -> None:
        """
        开始移动到目标位置
        
        Args:
            target: 目标位置（全局坐标）
        """
        self._target = target
        self._moving = True
        # 速度从最低开始
        self._current_speed = BEHAVIOR['move_min_speed']

    def update_target(self, target: QPoint) -> None:
        """
        动态更新移动目标点（仅在移动中生效）
        
        用于追踪动态目标（如跳跃中的雪豹）时持续刷新目标位置。
        
        Args:
            target: 新的目标位置
        """
        if self._moving:
            self._target = target

    def stop_move(self) -> None:
        """停止移动"""
        self._moving = False
        self._flipped = False
        self._current_speed = BEHAVIOR['move_min_speed']

    # ==================================================================
    # 帧更新
    # ==================================================================

    def update_tick(self, current_pos: QPoint) -> None:
        """
        TICK 事件更新 - 更新速度
        
        Args:
            current_pos: 当前位置
        """
        if not self._moving:
            return

        dx = self._target.x() - current_pos.x()
        dy = self._target.y() - current_pos.y()
        dist = (dx**2 + dy**2) ** 0.5

        # 到达目标时不处理，由 update_frame 处理
        if dist < 1:
            return

        # 更新方向
        new_flipped = dx < 0
        if self._flipped != new_flipped:
            self._flipped = new_flipped
            if self._on_direction_change:
                self._on_direction_change(new_flipped)

        # 速度插值逻辑
        self._update_speed(dist)

    def update_frame(self, current_pos: QPoint) -> Optional[QPoint]:
        """
        FRAME 事件更新 - 计算新位置
        
        Args:
            current_pos: 当前位置
            
        Returns:
            新位置，如果不需要移动返回 None
        """
        if not self._moving:
            return None

        dx = self._target.x() - current_pos.x()
        dy = self._target.y() - current_pos.y()
        dist = (dx**2 + dy**2) ** 0.5

        # 到达目标
        if dist < 1:
            self._moving = False
            self._flipped = False
            self._current_speed = BEHAVIOR['move_min_speed']
            
            if self._on_move_complete:
                self._on_move_complete()
            return None

        # 确保速度至少为最低速度
        speed = max(self._current_speed, BEHAVIOR['move_min_speed'])
        
        # 计算移动距离，确保不超过剩余距离
        move_distance = min(speed, dist)

        # 使用 round 而不是 int，避免向下取整导致的位置不更新
        nx = round(current_pos.x() + dx / dist * move_distance)
        ny = round(current_pos.y() + dy / dist * move_distance)
        new_pos = QPoint(nx, ny)

        if self._on_position_update:
            self._on_position_update(new_pos)

        return new_pos

    def _update_speed(self, dist: float) -> None:
        """
        更新移动速度（内部方法）
        
        速度插值逻辑：
        - 在减速范围内：速度接近最低时尝试加速，高于最低时减速
        - 不在减速范围：持续加速直到最高速度
        
        Args:
            dist: 当前距离目标的距离
        """
        decel_distance = BEHAVIOR['move_decel_distance']
        min_speed = BEHAVIOR['move_min_speed']
        max_speed = BEHAVIOR['move_max_speed']
        acceleration = BEHAVIOR['move_acceleration']

        if dist <= decel_distance:
            # 在减速范围内
            if self._current_speed > min_speed:
                # 速度大于最低速度，尝试减速
                self._current_speed -= acceleration
                if self._current_speed < min_speed:
                    self._current_speed = min_speed
            else:
                # 速度小于等于最低速度，尝试加速
                self._current_speed += acceleration
                if self._current_speed > max_speed:
                    self._current_speed = max_speed
        else:
            # 不在减速范围内，持续加速
            if self._current_speed < max_speed:
                self._current_speed += acceleration
                if self._current_speed > max_speed:
                    self._current_speed = max_speed

    # ==================================================================
    # 状态重置
    # ==================================================================

    def reset(self) -> None:
        """重置移动状态"""
        self._moving = False
        self._flipped = False
        self._current_speed = BEHAVIOR['move_min_speed']
        self._target = QPoint(0, 0)
