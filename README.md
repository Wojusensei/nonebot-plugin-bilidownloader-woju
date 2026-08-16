# nonebot-plugin-bilidownloader-woju

✨ 从B站视频下载音频/视频/封面的 NoneBot2 插件 ✨

## 功能

- `/mp3 视频链接/BV号` → 发送音频文件（M4A，自动选择最高音质）
- `/mp4 视频链接/BV号` → 发送视频文件（MP4）
- `/封面图 视频链接/BV号` → 发送封面图片

## 安装

```bash
nb plugin install nonebot-plugin-bilidownloader-woju
pip install nonebot-plugin-bilidownloader-woju
```

### 使用
在群聊或私聊中输入命令即可：

```
/mp3 BV1xx411c7mD
/mp4 https://www.bilibili.com/video/BV1xx411c7mD
/封面图 BV1xx411c7mD
```

`/mp3`、`/mp4` 通过群文件/私聊文件接口上传，需要协议端（Lagrange、NapCat 等）支持文件上传 API。

### 关于 /mp4 的画质

B站 DASH 视频流的画面与声音是分离的：

- **装有 ffmpeg**（推荐）：插件自动下载最高画质视频轨与音轨并无损合并，得到有声高清 MP4
- **未装 ffmpeg**：回退到自带音轨的流畅画质（360P 左右）MP4

### 配置
默认即装即用，可选配置项（写入 .env 文件）：

```ini
bilibili_downloader_max_file_mb=500
bilibili_downloader_ffmpeg_path=
```

- `bilibili_downloader_max_file_mb`：单文件下载大小上限（MB），超过则拒绝下载，默认 500
- `bilibili_downloader_ffmpeg_path`：ffmpeg 可执行文件路径，留空自动从 PATH 查找

## 0.3.0 更新日志

修复了导致插件完全不可用的多处缺陷：

- **修复致命 bug**：`CommandArg()` 参数注解错误导致 `/mp3` `/mp4` `/封面图` 在新版 nonebot2（2.4+ / pydantic v2）下完全无响应
- **修复** `get_download_url()` 缺少必填 `page_index` 参数（bilibili-api-python 17 起要求），此前每次下载必然报错
- **修复** DASH 解析路径错误（`data.dash` → 顶层 `dash`），此前永远提示“没有可用的音频流”
- **修复** `MessageSegment.file` 在 OneBot v11 中不存在导致发送文件必然报错，改用 `upload_group_file` / `upload_private_file` 接口
- **修复** `/mp4` 发送无声视频：装有 ffmpeg 时自动合并音视频轨；未装时回退为带声音的流畅画质
- **修复** 下载缺少 Referer/User-Agent 头导致部分 CDN 镜像 403
- 下载改为流式写盘，不再把整个文件读进内存；新增文件大小上限配置
- 临时文件改用随机文件名，避免并发冲突；异常路径统一清理临时文件
- 音频扩展名从 .mp3 修正为 .m4a（DASH 音频流实际格式）
- 修复 `requires-python` 与依赖冲突（Python 3.9 无法安装），现要求 Python ≥ 3.10
- 新增测试套件（nonebug + pytest）

## 开发

```bash
pip install -e ".[test]"
pytest
```

## 开源协议
MIT
