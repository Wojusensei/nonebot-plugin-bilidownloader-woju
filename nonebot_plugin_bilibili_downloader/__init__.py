import re
from pathlib import Path
from typing import Tuple, Optional
import httpx
from nonebot import get_driver, require
from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment
from nonebot.adapters.onebot.v11.event import GroupMessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.log import logger
from bilibili_api import video

from .config import Config

require("nonebot_plugin_localstore")
import nonebot_plugin_localstore as store

CACHE_DIR = store.get_plugin_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)


__plugin_meta__ = PluginMetadata(
    name="哔哩哔哩文件下载器",
    description="从B站视频下载音频(MP3)、视频(MP4)和封面图",
    usage=(
        "@机器人 /mp3 视频地址  → 发送音频文件\n"
        "@机器人 /mp4 视频地址  → 发送视频文件\n"
        "@机器人 /封面图 视频地址 → 发送封面图片"
    ),
    type="application",
    homepage="https://github.com/Wojusensei/nonebot-plugin-bilidownloader-woju",
    config=Config,
    supported_adapters={"~onebot.v11"},
)


def extract_bvid(url: str) -> Optional[str]:
    if re.match(r'^BV[0-9A-Za-z]{10}$', url):
        return url
    match = re.search(r'BV[0-9A-Za-z]{10}', url)
    return match.group() if match else None


def get_video_url_from_message(msg: str) -> str:
    bvid = extract_bvid(msg)
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}"
    return msg.strip()


async def get_video_info(bvid: str):
    v = video.Video(bvid=bvid)
    info = await v.get_info()
    return info


async def download_file(url: str, dest_path: Path) -> Tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            dest_path.write_bytes(resp.content)
            return True, ""
    except Exception as e:
        return False, str(e)


def clean_temp_file(path: Path):
    try:
        if path.exists():
            path.unlink()
    except Exception as e:
        logger.warning(f"清理临时文件失败 {path}: {e}")


def register_handlers():
    """延迟注册命令处理函数"""
    from nonebot import on_command
    
    mp3_cmd = on_command("/mp3", aliases={"mp3"}, priority=10, block=True)
    mp4_cmd = on_command("/mp4", aliases={"mp4"}, priority=10, block=True)
    cover_cmd = on_command("/封面图", aliases={"封面图"}, priority=10, block=True)
    
    @mp3_cmd.handle()
    async def handle_mp3(event: Event, args: str = None):
        from nonebot.params import CommandArg
        raw = CommandArg.extract_plain_text(args) if args else ""
        if not raw:
            await mp3_cmd.finish("请提供B站视频链接或BV号，例如：\n/mp3 BV1xx411c7mD")
        
        video_url = get_video_url_from_message(raw)
        bvid = extract_bvid(video_url)
        if not bvid:
            await mp3_cmd.finish("未能识别BV号，请检查链接是否正确")
        
        await mp3_cmd.send(f"🔍 正在获取视频信息：{bvid}")
        
        try:
            info = await get_video_info(bvid)
        except Exception as e:
            logger.error(f"获取视频信息失败: {e}")
            await mp3_cmd.finish(f"获取视频信息失败：{str(e)}")
        
        v = video.Video(bvid=bvid)
        try:
            download_info = await v.get_download_url()
            dash = download_info.get("data", {}).get("dash", {})
            audio_list = dash.get("audio")
            if not audio_list:
                await mp3_cmd.finish("该视频没有可用的音频流")
            best_audio = max(audio_list, key=lambda x: x.get("bandwidth", 0))
            audio_url = best_audio["baseUrl"]
        except Exception as e:
            await mp3_cmd.finish(f"获取音频地址失败：{str(e)}")
        
        title = info.get("title", bvid)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title)[:50]
        temp_file = CACHE_DIR / f"{bvid}_audio.mp3"
        await mp3_cmd.send("📥 正在下载音频文件，可能需要十几秒…")
        
        ok, err = await download_file(audio_url, temp_file)
        if not ok:
            await mp3_cmd.finish(f"下载失败：{err}")
        
        try:
            await mp3_cmd.send(MessageSegment.file(temp_file))
            await mp3_cmd.send(f"✅ 音频已发送：{safe_title}")
        except Exception as e:
            await mp3_cmd.send(f"发送文件时出错：{str(e)}")
        finally:
            clean_temp_file(temp_file)
    
    @mp4_cmd.handle()
    async def handle_mp4(event: Event, args: str = None):
        from nonebot.params import CommandArg
        raw = CommandArg.extract_plain_text(args) if args else ""
        if not raw:
            await mp4_cmd.finish("请提供B站视频链接或BV号，例如：\n/mp4 BV1xx411c7mD")
        
        video_url = get_video_url_from_message(raw)
        bvid = extract_bvid(video_url)
        if not bvid:
            await mp4_cmd.finish("未能识别BV号")
        
        await mp4_cmd.send(f"🔍 正在获取视频信息：{bvid}")
        try:
            info = await get_video_info(bvid)
        except Exception as e:
            await mp4_cmd.finish(f"获取视频信息失败：{str(e)}")
        
        v = video.Video(bvid=bvid)
        try:
            download_info = await v.get_download_url()
            dash = download_info.get("data", {}).get("dash", {})
            video_list = dash.get("video")
            if not video_list:
                await mp4_cmd.finish("该视频没有可用的视频流")
            best_video = max(video_list, key=lambda x: x.get("bandwidth", 0))
            video_url = best_video["baseUrl"]
        except Exception as e:
            await mp4_cmd.finish(f"获取视频地址失败：{str(e)}")
        
        title = info.get("title", bvid)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title)[:50]
        temp_file = CACHE_DIR / f"{bvid}_video.mp4"
        await mp4_cmd.send("📥 正在下载视频文件（可能时间较长）…")
        
        ok, err = await download_file(video_url, temp_file)
        if not ok:
            await mp4_cmd.finish(f"下载失败：{err}")
        
        try:
            await mp4_cmd.send(MessageSegment.file(temp_file))
            await mp4_cmd.send(f"✅ 视频已发送：{safe_title}")
        except Exception as e:
            await mp4_cmd.send(f"发送文件出错：{str(e)}")
        finally:
            clean_temp_file(temp_file)
    
    @cover_cmd.handle()
    async def handle_cover(event: Event, args: str = None):
        from nonebot.params import CommandArg
        raw = CommandArg.extract_plain_text(args) if args else ""
        if not raw:
            await cover_cmd.finish("请提供B站视频链接或BV号，例如：\n/封面图 BV1xx411c7mD")
        
        video_url = get_video_url_from_message(raw)
        bvid = extract_bvid(video_url)
        if not bvid:
            await cover_cmd.finish("未能识别BV号")
        
        await cover_cmd.send(f"🔍 正在获取封面：{bvid}")
        try:
            info = await get_video_info(bvid)
        except Exception as e:
            await cover_cmd.finish(f"获取信息失败：{str(e)}")
        
        cover_url = info.get("pic")
        if not cover_url:
            await cover_cmd.finish("没有找到封面图")
        
        temp_file = CACHE_DIR / f"{bvid}_cover.jpg"
        ok, err = await download_file(cover_url, temp_file)
        if not ok:
            await cover_cmd.finish(f"下载封面失败：{err}")
        
        try:
            await cover_cmd.send(MessageSegment.image(temp_file))
            await cover_cmd.send("✅ 封面图已发送")
        except Exception as e:
            await cover_cmd.send(f"发送图片出错：{str(e)}")
        finally:
            clean_temp_file(temp_file)


driver = get_driver()
driver.on_startup(register_handlers)