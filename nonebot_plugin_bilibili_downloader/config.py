from typing import Optional

from pydantic import BaseModel, Field


class Config(BaseModel):
    """Plugin Config"""

    bilibili_downloader_max_file_mb: int = Field(default=500, ge=1)
    """单个文件下载大小上限（MB），超过则拒绝下载"""

    bilibili_downloader_ffmpeg_path: Optional[str] = None
    """ffmpeg 可执行文件路径，留空则自动从 PATH 查找；
    安装 ffmpeg 后 /mp4 会合并音视频轨，否则回退为带声音的流畅版"""
