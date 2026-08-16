import asyncio
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Tuple

import httpx
from bilibili_api import video
from nonebot import get_plugin_config, on_command, require
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.log import logger
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from .config import Config

# ========================
# 1. localstore 顶层声明与缓存目录
# ========================
require("nonebot_plugin_localstore")
import nonebot_plugin_localstore as store

CACHE_DIR = store.get_plugin_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ========================
# 2. 插件元数据
# ========================
__plugin_meta__ = PluginMetadata(
    name="哔哩哔哩文件下载器",
    description="从B站视频下载音频(M4A)、视频(MP4)和封面图",
    usage=(
        "/mp3 视频链接/BV号 → 发送音频文件\n"
        "/mp4 视频链接/BV号 → 发送视频文件（装有 ffmpeg 时自动合并音轨）\n"
        "/封面图 视频链接/BV号 → 发送封面图片"
    ),
    type="application",
    homepage="https://github.com/Wojusensei/nonebot-plugin-bilidownloader-woju",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

# ========================
# 3. 配置读取
# ========================

config = get_plugin_config(Config)

# B站 CDN 部分镜像缺少 Referer 会返回 403
DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


# ========================
# 4. 工具函数
# ========================

def extract_bvid(text: str) -> Optional[str]:
    match = re.search(r"BV[0-9A-Za-z]{10}", text)
    return match.group() if match else None


def sanitize_filename(name: str, maxlen: int = 50) -> str:
    name = re.sub(r'[\\/*?:"<>|\r\n\t]', "", name).strip()
    return name[:maxlen].strip() or "bilibili"


def new_temp_path(suffix: str) -> Path:
    """在缓存目录生成唯一的临时文件路径，避免并发请求互相覆盖"""
    return CACHE_DIR / f"{uuid.uuid4().hex[:12]}{suffix}"


def find_ffmpeg() -> Optional[str]:
    return shutil.which(config.bilibili_downloader_ffmpeg_path or "ffmpeg")


async def get_video_info(bvid: str) -> dict:
    v = video.Video(bvid=bvid)
    return await v.get_info()


async def get_dash_streams(bvid: str) -> Tuple[Optional[str], Optional[str]]:
    """返回 DASH 最佳音质音频流与最佳画质视频流的下载地址

    bilibili-api-python 17 起 get_download_url 必须传 page_index，
    且返回结构中 dash 位于顶层（不在 data 下）。
    """
    v = video.Video(bvid=bvid)
    d = await v.get_download_url(page_index=0)
    dash = d.get("dash") or {}

    def best(streams) -> Optional[str]:
        if not streams:
            return None
        return max(streams, key=lambda x: x.get("bandwidth", 0))["baseUrl"]

    return best(dash.get("audio")), best(dash.get("video"))


async def get_html5_url(bvid: str) -> Optional[str]:
    """html5 模式返回单文件 MP4（自带音轨，清晰度较低），作为无 ffmpeg 时的回退"""
    v = video.Video(bvid=bvid)
    d = await v.get_download_url(page_index=0, html5=True)
    durl = d.get("durl") or []
    return durl[0]["url"] if durl else None


async def download_file(url: str, dest_path: Path) -> Tuple[bool, str]:
    """流式下载到磁盘，避免大文件占满内存；超过大小上限时中止"""
    max_bytes = config.bilibili_downloader_max_file_mb * 1024 * 1024
    try:
        timeout = httpx.Timeout(600, connect=15)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=DOWNLOAD_HEADERS) as resp:
                resp.raise_for_status()

                content_length = resp.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    size_mb = int(content_length) / 1024 / 1024
                    return False, f"文件过大（{size_mb:.0f}MB），超过 {config.bilibili_downloader_max_file_mb}MB 限制"

                downloaded = 0
                with dest_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(1024 * 256):
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            f.close()
                            dest_path.unlink(missing_ok=True)
                            return False, f"文件超过 {config.bilibili_downloader_max_file_mb}MB 限制，已中止"
                        f.write(chunk)
        return True, ""
    except Exception as e:
        clean_temp_file(dest_path)
        return False, str(e)


async def mux_av(video_path: Path, audio_path: Path, out_path: Path) -> Tuple[bool, str]:
    """用 ffmpeg 无损合并视频轨与音频轨"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "未安装 ffmpeg"
    try:
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path),
            "-c", "copy", str(out_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            return False, stderr.decode(errors="ignore")[-300:]
        return True, ""
    except Exception as e:
        return False, str(e)


def clean_temp_file(path: Path):
    try:
        path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"清理临时文件失败 {path}: {e}")


async def send_file(bot: Bot, event: Event, path: Path, name: str):
    """通过群文件/私聊文件接口上传文件（OneBot v11 没有文件消息段）"""
    if isinstance(event, GroupMessageEvent):
        await bot.upload_group_file(group_id=event.group_id, file=str(path), name=name)
    elif isinstance(event, PrivateMessageEvent):
        await bot.upload_private_file(user_id=event.user_id, file=str(path), name=name)
    else:
        raise RuntimeError("当前会话类型不支持发送文件")


# ========================
# 5. 命令注册
# ========================

mp3_cmd = on_command("mp3", priority=10, block=True)
mp4_cmd = on_command("mp4", priority=10, block=True)
cover_cmd = on_command("封面图", priority=10, block=True)


# ========================
# 6. 命令处理函数
# ========================

@mp3_cmd.handle()
async def handle_mp3(bot: Bot, event: Event, args: Message = CommandArg()):
    raw = args.extract_plain_text().strip()
    if not raw:
        await mp3_cmd.finish("请提供B站视频链接或BV号，例如：\n/mp3 BV1xx411c7mD")

    bvid = extract_bvid(raw)
    if not bvid:
        await mp3_cmd.finish("未能识别BV号，请检查链接是否正确")

    await mp3_cmd.send(f"🔍 正在获取视频信息：{bvid}")
    try:
        info = await get_video_info(bvid)
    except Exception as e:
        logger.error(f"获取视频信息失败: {e}")
        await mp3_cmd.finish(f"获取视频信息失败：{e}")

    try:
        audio_url, _ = await get_dash_streams(bvid)
    except Exception as e:
        logger.error(f"获取音频地址失败: {e}")
        await mp3_cmd.finish(f"获取音频地址失败：{e}")
    if not audio_url:
        await mp3_cmd.finish("该视频没有可用的音频流")

    safe_title = sanitize_filename(info.get("title", bvid))
    temp_file = new_temp_path(".m4a")
    try:
        await mp3_cmd.send("📥 正在下载音频文件，可能需要十几秒…")
        ok, err = await download_file(audio_url, temp_file)
        if not ok:
            await mp3_cmd.finish(f"下载失败：{err}")

        try:
            await send_file(bot, event, temp_file, f"{safe_title}.m4a")
            await mp3_cmd.send(f"✅ 音频已发送：{safe_title}")
        except Exception as e:
            logger.error(f"发送音频失败: {e}")
            await mp3_cmd.send(f"发送文件失败（协议端可能不支持文件上传）：{e}")
    finally:
        clean_temp_file(temp_file)
    await mp3_cmd.finish()


@mp4_cmd.handle()
async def handle_mp4(bot: Bot, event: Event, args: Message = CommandArg()):
    raw = args.extract_plain_text().strip()
    if not raw:
        await mp4_cmd.finish("请提供B站视频链接或BV号，例如：\n/mp4 BV1xx411c7mD")

    bvid = extract_bvid(raw)
    if not bvid:
        await mp4_cmd.finish("未能识别BV号，请检查链接是否正确")

    await mp4_cmd.send(f"🔍 正在获取视频信息：{bvid}")
    try:
        info = await get_video_info(bvid)
    except Exception as e:
        logger.error(f"获取视频信息失败: {e}")
        await mp4_cmd.finish(f"获取视频信息失败：{e}")

    safe_title = sanitize_filename(info.get("title", bvid))
    use_ffmpeg = find_ffmpeg() is not None

    if use_ffmpeg:
        # DASH 音视频分离，需要 ffmpeg 合并
        try:
            audio_url, video_url = await get_dash_streams(bvid)
        except Exception as e:
            logger.error(f"获取视频地址失败: {e}")
            await mp4_cmd.finish(f"获取视频地址失败：{e}")

        if not video_url:
            await mp4_cmd.finish("该视频没有可用的视频流")

        video_tmp = new_temp_path(".m4v")
        audio_tmp = new_temp_path(".m4a")
        out_file = new_temp_path(".mp4")
        try:
            await mp4_cmd.send("📥 正在下载视频（高清画质，体积较大，请耐心等待）…")
            ok, err = await download_file(video_url, video_tmp)
            if not ok:
                await mp4_cmd.finish(f"下载视频失败：{err}")

            has_audio = False
            if audio_url:
                ok, err = await download_file(audio_url, audio_tmp)
                if not ok:
                    logger.warning(f"下载音频失败（将发送无声视频）：{err}")
                else:
                    has_audio = True

            if has_audio:
                await mp4_cmd.send("🎚 正在合并音视频轨…")
                ok, err = await mux_av(video_tmp, audio_tmp, out_file)
                if not ok:
                    logger.error(f"合并音视频失败: {err}")
                    await mp4_cmd.finish(f"合并音视频失败：{err}")
            else:
                video_tmp.rename(out_file)

            try:
                await send_file(bot, event, out_file, f"{safe_title}.mp4")
                await mp4_cmd.send(f"✅ 视频已发送：{safe_title}")
            except Exception as e:
                logger.error(f"发送视频失败: {e}")
                await mp4_cmd.send(f"发送文件失败（协议端可能不支持文件上传）：{e}")
        finally:
            clean_temp_file(video_tmp)
            clean_temp_file(audio_tmp)
            clean_temp_file(out_file)
        await mp4_cmd.finish()
        return

    # 无 ffmpeg：回退 html5 单文件 MP4（自带音轨，流畅画质）
    try:
        html5_url = await get_html5_url(bvid)
    except Exception as e:
        logger.error(f"获取视频地址失败: {e}")
        await mp4_cmd.finish(f"获取视频地址失败：{e}")
    if not html5_url:
        await mp4_cmd.finish("该视频没有可用的视频流")

    out_file = new_temp_path(".mp4")
    try:
        await mp4_cmd.send("📥 正在下载视频（未安装 ffmpeg，发送带声音的流畅画质）…")
        ok, err = await download_file(html5_url, out_file)
        if not ok:
            await mp4_cmd.finish(f"下载失败：{err}")

        try:
            await send_file(bot, event, out_file, f"{safe_title}.mp4")
            await mp4_cmd.send(f"✅ 视频已发送：{safe_title}")
        except Exception as e:
            logger.error(f"发送视频失败: {e}")
            await mp4_cmd.send(f"发送文件失败（协议端可能不支持文件上传）：{e}")
    finally:
        clean_temp_file(out_file)
    await mp4_cmd.finish()


@cover_cmd.handle()
async def handle_cover(event: Event, args: Message = CommandArg()):
    raw = args.extract_plain_text().strip()
    if not raw:
        await cover_cmd.finish("请提供B站视频链接或BV号，例如：\n/封面图 BV1xx411c7mD")

    bvid = extract_bvid(raw)
    if not bvid:
        await cover_cmd.finish("未能识别BV号，请检查链接是否正确")

    await cover_cmd.send(f"🔍 正在获取封面：{bvid}")
    try:
        info = await get_video_info(bvid)
    except Exception as e:
        logger.error(f"获取信息失败: {e}")
        await cover_cmd.finish(f"获取信息失败：{e}")

    cover_url = info.get("pic")
    if not cover_url:
        await cover_cmd.finish("没有找到封面图")

    temp_file = new_temp_path(".jpg")
    try:
        ok, err = await download_file(cover_url, temp_file)
        if not ok:
            await cover_cmd.finish(f"下载封面失败：{err}")

        try:
            await cover_cmd.send(MessageSegment.image(temp_file))
            await cover_cmd.send("✅ 封面图已发送")
        except Exception as e:
            logger.error(f"发送图片失败: {e}")
            await cover_cmd.send(f"发送图片出错：{e}")
    finally:
        clean_temp_file(temp_file)
    await cover_cmd.finish()
