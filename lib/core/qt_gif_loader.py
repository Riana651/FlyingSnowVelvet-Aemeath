"""GIF动画加载和管理模块 (PyQt5版)"""
import os
from PyQt5.QtGui import QImage
from PyQt5.QtCore import Qt
from PIL import Image, ImageSequence

from lib.core.logger import get_logger
logger = get_logger(__name__)


class GifLoader:
    """
    GIF文件加载器
    将GIF每一帧加载为 QImage 列表，方便翻转、缩放等操作。
    """

    def __init__(self, gif_files: list[str]):
        self.gif_files = gif_files
        # { 'idle': [QImage, ...], 'happy': [...], ... }
        self.gifs: dict[str, list[QImage]] = {}

    # ------------------------------------------------------------------
    def load_all(self) -> dict[str, list[QImage]]:
        """加载所有GIF文件，返回帧字典。"""
        logger.info('工作目录: %s', os.getcwd())
        logger.info('开始加载 GIF 文件...')

        for filename in self.gif_files:
            if os.path.exists(filename):
                frames = self._load_frames(filename)
                if frames:
                    key = os.path.basename(filename).replace('.gif', '')
                    self.gifs[key] = frames
                    logger.info('  ✓ %s  (%d 帧)', filename, len(frames))
                else:
                    logger.warning('  ✗ %s  加载失败', filename)
            else:
                logger.warning('  - %s  文件不存在', filename)

        logger.info('共加载 %d 个动画\n', len(self.gifs))
        return self.gifs

    # ------------------------------------------------------------------
    def _load_frames(self, filename: str) -> list[QImage]:
        """用 Pillow 逐帧读取 GIF，转换为 QImage（RGBA），正确处理帧叠加。"""
        frames = []
        try:
            img = Image.open(filename)
            # 获取 GIF 的尺寸
            size = img.size
            # 创建累积画布（RGBA 模式）
            canvas = Image.new('RGBA', size, (0, 0, 0, 0))
            
            for frame in ImageSequence.Iterator(img):
                # 获取 disposal method
                disposal = frame.info.get('disposal', 2)
                
                # 获取帧的偏移位置
                offset = frame.info.get('offset', (0, 0))
                
                # 将当前帧转换为 RGBA
                frame_rgba = frame.convert('RGBA')
                
                # 处理 disposal method
                if disposal == 2:
                    # 恢复到背景色（透明）
                    canvas = Image.new('RGBA', size, (0, 0, 0, 0))
                elif disposal == 3:
                    # 恢复到上一帧（保留累积内容）
                    pass
                else:
                    # disposal == 0 或 1，保留累积内容
                    pass
                
                # 将当前帧绘制到累积画布上
                canvas.paste(frame_rgba, offset, frame_rgba)
                
                # 转换为 QImage
                w, h = canvas.size
                data = canvas.tobytes('raw', 'RGBA')
                qimg = QImage(data, w, h, QImage.Format_RGBA8888).copy()
                frames.append(qimg)
                
        except Exception as e:
            logger.error('    加载 %s 出错: %s', filename, e)
        return frames

    # ------------------------------------------------------------------
    def get(self, name: str) -> list[QImage]:
        return self.gifs.get(name, [])

    def has(self, name: str) -> bool:
        return name in self.gifs


# ------------------------------------------------------------------
# 图像工具函数
# ------------------------------------------------------------------

def scale_frame(frame: QImage, size: tuple[int, int]) -> QImage:
    """
    用最近邻插值缩放（无抗锯齿），保持像素风格。

    Args:
        frame: 原始 QImage
        size:  目标尺寸 (width, height)
    """
    return frame.scaled(size[0], size[1], Qt.IgnoreAspectRatio, Qt.FastTransformation)


def flip_frame(frame: QImage) -> QImage:
    """水平翻转 QImage。"""
    return frame.mirrored(horizontal=True, vertical=False)
