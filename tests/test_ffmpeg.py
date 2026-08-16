"""ffmpeg 合并功能测试（本机无 ffmpeg 时自动跳过）"""
import shutil
from pathlib import Path

import pytest

import nonebot_plugin_bilibili_downloader as plugin

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="本机未安装 ffmpeg"
)


@pytest.fixture
def sample_av(tmp_path: Path):
    """用 ffmpeg 生成 1 秒的测试视频轨与音频轨"""
    video_file = tmp_path / "v.m4v"
    audio_file = tmp_path / "a.m4a"
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=128x96:rate=10",
         "-c:v", "libx264", str(video_file)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", str(audio_file)],
        check=True, capture_output=True,
    )
    return video_file, audio_file


async def test_mux_av_success(tmp_path, sample_av):
    video_file, audio_file = sample_av
    out = tmp_path / "out.mp4"
    ok, err = await plugin.mux_av(video_file, audio_file, out)
    assert ok, err
    assert out.exists() and out.stat().st_size > 0


async def test_mux_av_bad_input(tmp_path):
    bad_video = tmp_path / "bad.m4v"
    bad_video.write_bytes(b"not a video")
    bad_audio = tmp_path / "bad.m4a"
    bad_audio.write_bytes(b"not an audio")
    out = tmp_path / "out.mp4"
    ok, err = await plugin.mux_av(bad_video, bad_audio, out)
    assert not ok
    assert err  # 应返回 ffmpeg 的错误输出
