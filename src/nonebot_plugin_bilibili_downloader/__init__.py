import re
from pathlib import Path
from typing import Tuple, Optional
import httpx
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.log import logger
from bilibili_api import video
from nonebot_plugin_localstore import get_cache_dir

from .config import Config


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


CACHE_DIR = get_cache_dir("nonebot_plugin_bilibili_downloader")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


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
        logger.warning(f"������ʱ�ļ�ʧ�� {path}: {e}")


mp3_cmd = on_command("/mp3", aliases={"mp3"}, priority=10, block=True)
mp4_cmd = on_command("/mp4", aliases={"mp4"}, priority=10, block=True)
cover_cmd = on_command("/����ͼ", aliases={"����ͼ"}, priority=10, block=True)


@mp3_cmd.handle()
async def handle_mp3(event: Event, args: str = CommandArg()):
    raw = args.extract_plain_text().strip()
    if not raw:
        await mp3_cmd.finish("���ṩBվ��Ƶ���ӻ�BV�ţ����磺\n/mp3 BV1xx411c7mD")

    video_url = get_video_url_from_message(raw)
    bvid = extract_bvid(video_url)
    if not bvid:
        await mp3_cmd.finish("δ��ʶ��BV�ţ����������Ƿ���ȷ")

    await mp3_cmd.send(f"?? ���ڻ�ȡ��Ƶ��Ϣ��{bvid}")

    try:
        info = await get_video_info(bvid)
    except Exception as e:
        logger.error(f"��ȡ��Ƶ��Ϣʧ��: {e}")
        await mp3_cmd.finish(f"��ȡ��Ƶ��Ϣʧ�ܣ�{str(e)}")

    v = video.Video(bvid=bvid)
    try:
        download_info = await v.get_download_url()
        dash = download_info.get("data", {}).get("dash", {})
        audio_list = dash.get("audio")
        if not audio_list:
            await mp3_cmd.finish("����Ƶû�п��õ���Ƶ��")
        best_audio = max(audio_list, key=lambda x: x.get("bandwidth", 0))
        audio_url = best_audio["baseUrl"]
    except Exception as e:
        await mp3_cmd.finish(f"��ȡ��Ƶ��ַʧ�ܣ�{str(e)}")

    title = info.get("title", bvid)
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)[:50]
    temp_file = CACHE_DIR / f"{bvid}_audio.mp3"
    await mp3_cmd.send("?? ����������Ƶ�ļ���������Ҫʮ���롭")

    ok, err = await download_file(audio_url, temp_file)
    if not ok:
        await mp3_cmd.finish(f"����ʧ�ܣ�{err}")

    try:
        await mp3_cmd.send(MessageSegment.file(temp_file))
        await mp3_cmd.send(f"? ��Ƶ�ѷ��ͣ�{safe_title}")
    except Exception as e:
        await mp3_cmd.send(f"�����ļ�ʱ������{str(e)}")
    finally:
        clean_temp_file(temp_file)


@mp4_cmd.handle()
async def handle_mp4(event: Event, args: str = CommandArg()):
    raw = args.extract_plain_text().strip()
    if not raw:
        await mp4_cmd.finish("���ṩBվ��Ƶ���ӻ�BV�ţ����磺\n/mp4 BV1xx411c7mD")

    video_url = get_video_url_from_message(raw)
    bvid = extract_bvid(video_url)
    if not bvid:
        await mp4_cmd.finish("δ��ʶ��BV��")

    await mp4_cmd.send(f"?? ���ڻ�ȡ��Ƶ��Ϣ��{bvid}")
    try:
        info = await get_video_info(bvid)
    except Exception as e:
        await mp4_cmd.finish(f"��ȡ��Ƶ��Ϣʧ�ܣ�{str(e)}")

    v = video.Video(bvid=bvid)
    try:
        download_info = await v.get_download_url()
        dash = download_info.get("data", {}).get("dash", {})
        video_list = dash.get("video")
        if not video_list:
            await mp4_cmd.finish("����Ƶû�п��õ���Ƶ��")
        best_video = max(video_list, key=lambda x: x.get("bandwidth", 0))
        video_url = best_video["baseUrl"]
    except Exception as e:
        await mp4_cmd.finish(f"��ȡ��Ƶ��ַʧ�ܣ�{str(e)}")

    title = info.get("title", bvid)
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)[:50]
    temp_file = CACHE_DIR / f"{bvid}_video.mp4"
    await mp4_cmd.send("?? ����������Ƶ�ļ�������ʱ��ϳ�����")

    ok, err = await download_file(video_url, temp_file)
    if not ok:
        await mp4_cmd.finish(f"����ʧ�ܣ�{err}")

    try:
        await mp4_cmd.send(MessageSegment.file(temp_file))
        await mp4_cmd.send(f"? ��Ƶ�ѷ��ͣ�{safe_title}")
    except Exception as e:
        await mp4_cmd.send(f"�����ļ�������{str(e)}")
    finally:
        clean_temp_file(temp_file)


@cover_cmd.handle()
async def handle_cover(event: Event, args: str = CommandArg()):
    raw = args.extract_plain_text().strip()
    if not raw:
        await cover_cmd.finish("���ṩBվ��Ƶ���ӻ�BV�ţ����磺\n/����ͼ BV1xx411c7mD")

    video_url = get_video_url_from_message(raw)
    bvid = extract_bvid(video_url)
    if not bvid:
        await cover_cmd.finish("δ��ʶ��BV��")

    await cover_cmd.send(f"?? ���ڻ�ȡ���棺{bvid}")
    try:
        info = await get_video_info(bvid)
    except Exception as e:
        await cover_cmd.finish(f"��ȡ��Ϣʧ�ܣ�{str(e)}")

    cover_url = info.get("pic")
    if not cover_url:
        await cover_cmd.finish("û���ҵ�����ͼ")

    temp_file = CACHE_DIR / f"{bvid}_cover.jpg"
    ok, err = await download_file(cover_url, temp_file)
    if not ok:
        await cover_cmd.finish(f"���ط���ʧ�ܣ�{err}")

    try:
        await cover_cmd.send(MessageSegment.image(temp_file))
        await cover_cmd.send("? ����ͼ�ѷ���")
    except Exception as e:
        await cover_cmd.send(f"����ͼƬ������{str(e)}")
    finally:
        clean_temp_file(temp_file)
