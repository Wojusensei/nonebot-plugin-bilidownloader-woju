"""命令处理测试（nonebug，跨适配器发送统一走 uniseg）"""
from pathlib import Path

import nonebot_plugin_bilibili_downloader as plugin
from nonebot.adapters.onebot.v11 import Bot as OB11Bot, Message
from nonebot.adapters.onebot.v11.event import GroupMessageEvent
from nonebot.adapters.milky import Bot as MilkyBot
from nonebot.adapters.milky.config import ClientInfo
from nonebot.adapters.milky.event import GroupMessageEvent as MilkyGroupEvent

from nonebot_plugin_bilibili_downloader import mp3_cmd, mp4_cmd, cover_cmd


def make_group_event(text: str, group_id: int = 10000, user_id: int = 20000) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1122,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=1234,
        message=Message(text),
        raw_message=text,
        font=0,
        sender={"user_id": user_id, "nickname": "test"},
        group_id=group_id,
    )


def make_milky_group_event(text: str, group_id: int = 438, user_id: int = 5678) -> MilkyGroupEvent:
    return MilkyGroupEvent.model_validate({
        "time": 1122,
        "self_id": 1,
        "data": {
            "message_scene": "group",
            "peer_id": group_id,
            "message_seq": 1234,
            "sender_id": user_id,
            "time": 1122,
            "segments": [{"type": "text", "data": {"text": text}}],
        },
    })


def fake_file_writer(content: bytes = b"fake"):
    async def _download(url: str, dest: Path):
        dest.write_bytes(content)
        return True, ""
    return _download


class FakeUni:
    """打桩 UniMessage：记录文件/图片发送调用，send() 直接返回"""

    sent: list = []

    @staticmethod
    def _record(kind, **kwargs):
        FakeUni.sent.append((kind, kwargs))

    @classmethod
    def file(cls, path=None, name="file.bin", **kw):
        cls._record("file", path=path, name=name)

        class _Sender:
            async def send(self, **kwargs):
                return None
        return _Sender()

    @classmethod
    def image(cls, path=None, **kw):
        cls._record("image", path=path)

        class _Sender:
            async def send(self, **kwargs):
                return None
        return _Sender()

    @classmethod
    def reset(cls):
        cls.sent = []


class TestMp3:
    async def test_missing_arg(self, app):
        """回归：args 注解错误会让命令无响应"""
        async with app.test_matcher() as ctx:
            adapter = ctx.create_adapter()
            bot = ctx.create_bot(adapter=adapter, base=OB11Bot)
            event = make_group_event("/mp3")
            ctx.receive_event(bot, event)
            ctx.should_call_send(
                event, "请提供B站视频链接或BV号，例如：\n/mp3 BV1xx411c7mD", result=None, bot=bot
            )
            ctx.should_finished(mp3_cmd)

    async def test_invalid_bv(self, app):
        async with app.test_matcher() as ctx:
            adapter = ctx.create_adapter()
            bot = ctx.create_bot(adapter=adapter, base=OB11Bot)
            event = make_group_event("/mp3 看看这个")
            ctx.receive_event(bot, event)
            ctx.should_call_send(event, "未能识别BV号，请检查链接是否正确", result=None, bot=bot)
            ctx.should_finished(mp3_cmd)

    async def test_group_happy_path(self, app, monkeypatch):
        async def fake_info(bvid: str):
            return {"title": "测试:视频/标题", "pic": ""}

        async def fake_streams(bvid: str):
            return "http://audio.example/a.m4s", "http://video.example/v.m4s"

        monkeypatch.setattr(plugin, "get_video_info", fake_info)
        monkeypatch.setattr(plugin, "get_dash_streams", fake_streams)
        monkeypatch.setattr(plugin, "download_file", fake_file_writer(b"ID3-audio"))
        monkeypatch.setattr(plugin, "UniMessage", FakeUni)
        FakeUni.reset()

        async with app.test_matcher() as ctx:
            adapter = ctx.create_adapter()
            bot = ctx.create_bot(adapter=adapter, base=OB11Bot)
            event = make_group_event("/mp3 BV1GJ411x7h7")
            ctx.receive_event(bot, event)
            ctx.should_call_send(event, "🔍 正在获取视频信息：BV1GJ411x7h7", result=None, bot=bot)
            ctx.should_call_send(event, "📥 正在下载音频文件，可能需要十几秒…", result=None, bot=bot)
            ctx.should_call_send(event, "✅ 音频已发送：测试视频标题", result=None, bot=bot)
            ctx.should_finished(mp3_cmd)

        # 文件通过 uniseg 发送：跨适配器，无需区分群/私聊
        assert FakeUni.sent and FakeUni.sent[0][0] == "file"
        assert FakeUni.sent[0][1]["name"] == "测试视频标题.m4a"

    async def test_milky_command_path(self, app, monkeypatch):
        """Milky 群消息下命令解析与发送路径可用"""
        async def fake_info(bvid: str):
            return {"title": "私聊测试", "pic": ""}

        async def fake_streams(bvid: str):
            return "http://audio.example/a.m4s", None

        monkeypatch.setattr(plugin, "get_video_info", fake_info)
        monkeypatch.setattr(plugin, "get_dash_streams", fake_streams)
        monkeypatch.setattr(plugin, "download_file", fake_file_writer(b"audio"))
        monkeypatch.setattr(plugin, "UniMessage", FakeUni)
        FakeUni.reset()

        async with app.test_matcher() as ctx:
            adapter = ctx.create_adapter()
            bot = ctx.create_bot(adapter=adapter, base=MilkyBot, self_id="1", info=ClientInfo())
            event = make_milky_group_event("/mp3 BV1GJ411x7h7")
            ctx.receive_event(bot, event)
            ctx.should_call_send(event, "🔍 正在获取视频信息：BV1GJ411x7h7", result=None, bot=bot)
            ctx.should_call_send(event, "📥 正在下载音频文件，可能需要十几秒…", result=None, bot=bot)
            ctx.should_call_send(event, "✅ 音频已发送：私聊测试", result=None, bot=bot)
            ctx.should_finished(mp3_cmd)

        assert FakeUni.sent and FakeUni.sent[0][1]["name"] == "私聊测试.m4a"


class TestMp4:
    async def test_no_ffmpeg_fallback(self, app, monkeypatch):
        """无 ffmpeg 时回退 html5 单文件 MP4"""
        monkeypatch.setattr(plugin, "find_ffmpeg", lambda: None)

        async def fake_info(bvid: str):
            return {"title": "回退测试", "pic": ""}

        async def fake_html5(bvid: str):
            return "http://video.example/html5.mp4"

        monkeypatch.setattr(plugin, "get_video_info", fake_info)
        monkeypatch.setattr(plugin, "get_html5_url", fake_html5)
        monkeypatch.setattr(plugin, "download_file", fake_file_writer(b"mp4data"))
        monkeypatch.setattr(plugin, "UniMessage", FakeUni)
        FakeUni.reset()

        async with app.test_matcher() as ctx:
            adapter = ctx.create_adapter()
            bot = ctx.create_bot(adapter=adapter, base=OB11Bot)
            event = make_group_event("/mp4 BV1GJ411x7h7")
            ctx.receive_event(bot, event)
            ctx.should_call_send(event, "🔍 正在获取视频信息：BV1GJ411x7h7", result=None, bot=bot)
            ctx.should_call_send(
                event, "📥 正在下载视频（未安装 ffmpeg，发送带声音的流畅画质）…", result=None, bot=bot
            )
            ctx.should_call_send(event, "✅ 视频已发送：回退测试", result=None, bot=bot)
            ctx.should_finished(mp4_cmd)

        assert FakeUni.sent and FakeUni.sent[0][1]["name"] == "回退测试.mp4"

    async def test_with_ffmpeg_mux(self, app, monkeypatch, tmp_path):
        """有 ffmpeg 时走 DASH + 合并路径（mux 用假实现，真实 mux 见 test_ffmpeg）"""
        monkeypatch.setattr(plugin, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")

        async def fake_info(bvid: str):
            return {"title": "合并测试", "pic": ""}

        async def fake_streams(bvid: str):
            return "http://audio.example/a.m4s", "http://video.example/v.m4s"

        async def fake_mux(v: Path, a: Path, out: Path):
            out.write_bytes(b"muxed")
            return True, ""

        monkeypatch.setattr(plugin, "get_video_info", fake_info)
        monkeypatch.setattr(plugin, "get_dash_streams", fake_streams)
        monkeypatch.setattr(plugin, "mux_av", fake_mux)
        monkeypatch.setattr(plugin, "download_file", fake_file_writer(b"data"))
        monkeypatch.setattr(plugin, "UniMessage", FakeUni)
        FakeUni.reset()

        async with app.test_matcher() as ctx:
            adapter = ctx.create_adapter()
            bot = ctx.create_bot(adapter=adapter, base=OB11Bot)
            event = make_group_event("/mp4 BV1GJ411x7h7")
            ctx.receive_event(bot, event)
            ctx.should_call_send(event, "🔍 正在获取视频信息：BV1GJ411x7h7", result=None, bot=bot)
            ctx.should_call_send(
                event, "📥 正在下载视频（高清画质，体积较大，请耐心等待）…", result=None, bot=bot
            )
            ctx.should_call_send(event, "🎚 正在合并音视频轨…", result=None, bot=bot)
            ctx.should_call_send(event, "✅ 视频已发送：合并测试", result=None, bot=bot)
            ctx.should_finished(mp4_cmd)

        assert FakeUni.sent and FakeUni.sent[0][1]["name"] == "合并测试.mp4"


class TestCover:
    async def test_happy_path(self, app, monkeypatch):
        async def fake_info(bvid: str):
            return {"title": "封面测试", "pic": "http://pic.example/c.jpg"}

        monkeypatch.setattr(plugin, "get_video_info", fake_info)
        monkeypatch.setattr(plugin, "download_file", fake_file_writer(b"jpgdata"))
        monkeypatch.setattr(plugin, "UniMessage", FakeUni)
        FakeUni.reset()

        async with app.test_matcher() as ctx:
            adapter = ctx.create_adapter()
            bot = ctx.create_bot(adapter=adapter, base=OB11Bot)
            event = make_group_event("/封面图 BV1GJ411x7h7")
            ctx.receive_event(bot, event)
            ctx.should_call_send(event, "🔍 正在获取封面：BV1GJ411x7h7", result=None, bot=bot)
            ctx.should_call_send(event, "✅ 封面图已发送", result=None, bot=bot)
            ctx.should_finished(cover_cmd)

        assert FakeUni.sent and FakeUni.sent[0][0] == "image"
        # 发送完毕后临时文件应被清理
        assert not Path(FakeUni.sent[0][1]["path"]).exists()

    async def test_no_pic(self, app, monkeypatch):
        async def fake_info(bvid: str):
            return {"title": "无图", "pic": ""}

        monkeypatch.setattr(plugin, "get_video_info", fake_info)

        async with app.test_matcher() as ctx:
            adapter = ctx.create_adapter()
            bot = ctx.create_bot(adapter=adapter, base=OB11Bot)
            event = make_group_event("/封面图 BV1GJ411x7h7")
            ctx.receive_event(bot, event)
            ctx.should_call_send(event, "🔍 正在获取封面：BV1GJ411x7h7", result=None, bot=bot)
            ctx.should_call_send(event, "没有找到封面图", result=None, bot=bot)
            ctx.should_finished(cover_cmd)
