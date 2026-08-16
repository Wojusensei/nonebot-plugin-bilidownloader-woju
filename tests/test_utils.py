"""纯函数与下载逻辑单元测试"""
import asyncio
import shutil

import nonebot_plugin_bilibili_downloader as plugin


class TestExtractBvid:
    def test_pure_bv(self):
        assert plugin.extract_bvid("BV1xx411c7mD") == "BV1xx411c7mD"

    def test_bv_in_url(self):
        assert (
            plugin.extract_bvid("https://www.bilibili.com/video/BV1GJ411x7h7?p=1")
            == "BV1GJ411x7h7"
        )

    def test_bv_in_text(self):
        assert plugin.extract_bvid("看看 https://b23.tv/xxx 里的 BV1GJ411x7h7") == "BV1GJ411x7h7"

    def test_none(self):
        assert plugin.extract_bvid("https://www.bilibili.com/video/av170001") is None
        assert plugin.extract_bvid("没有链接") is None

    def test_too_short_bv(self):
        # 不足 10 位不应被识别
        assert plugin.extract_bvid("BV1xx411c7") is None


class TestSanitizeFilename:
    def test_removes_special_chars(self):
        assert plugin.sanitize_filename('a/b\\c*d?e"f<g>h|i') == "abcdefghi"

    def test_removes_newlines(self):
        assert plugin.sanitize_filename("标题\n换行\t制表") == "标题换行制表"

    def test_truncates(self):
        assert len(plugin.sanitize_filename("长" * 100)) == 50

    def test_empty_fallback(self):
        assert plugin.sanitize_filename("///") == "bilibili"


class TestTempPath:
    def test_unique(self):
        paths = {str(plugin.new_temp_path(".m4a")) for _ in range(50)}
        assert len(paths) == 50

    def test_suffix(self):
        assert plugin.new_temp_path(".mp4").suffix == ".mp4"


class TestFindFfmpeg:
    def test_autodetect(self):
        if shutil.which("ffmpeg"):
            assert plugin.find_ffmpeg() is not None
        # 未配置路径时不应抛异常


class LocalHTTPServer:
    """测试用的极简 HTTP 服务器，返回固定大小的字节流"""

    def __init__(self, size: int, content_length: bool = True):
        self.size = size
        self.content_length = content_length
        self.server = None

    async def start(self):
        async def handler(reader, writer):
            await reader.readline()  # request line
            while (line := await reader.readline()) not in (b"\r\n", b"", None):
                pass
            body = b"x" * self.size
            headers = f"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
            if self.content_length:
                headers += f"Content-Length: {len(body)}\r\n"
            headers += "Connection: close\r\n\r\n"
            writer.write(headers.encode() + body)
            await writer.drain()
            writer.close()

        self.server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}/file"

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()


class TestDownload:
    async def test_download_small_file(self, tmp_path):
        srv = LocalHTTPServer(size=1024)
        url = await srv.start()
        try:
            dest = tmp_path / "out.bin"
            ok, err = await plugin.download_file(url, dest)
            assert ok, err
            assert dest.stat().st_size == 1024
        finally:
            await srv.stop()

    async def test_download_size_limit_by_content_length(self, tmp_path, monkeypatch):
        """响应头 Content-Length 超限应被直接拒绝"""
        monkeypatch.setattr(plugin.config, "bilibili_downloader_max_file_mb", 1)
        srv = LocalHTTPServer(size=3 * 1024 * 1024)
        url = await srv.start()
        try:
            dest = tmp_path / "out.bin"
            ok, err = await plugin.download_file(url, dest)
            assert not ok
            assert "过大" in err and "限制" in err
            assert not dest.exists()
        finally:
            await srv.stop()

    async def test_download_size_limit_streaming_abort(self, tmp_path, monkeypatch):
        """无 Content-Length 时流式下载超限应中止"""
        monkeypatch.setattr(plugin.config, "bilibili_downloader_max_file_mb", 1)
        srv = LocalHTTPServer(size=3 * 1024 * 1024, content_length=False)
        url = await srv.start()
        try:
            dest = tmp_path / "out.bin"
            ok, err = await plugin.download_file(url, dest)
            assert not ok
            assert "限制" in err
            assert not dest.exists()
        finally:
            await srv.stop()
