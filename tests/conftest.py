import os
import sys
import tempfile
from pathlib import Path

# 插件根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# localstore 会在插件导入时确定数据目录，先重定向到临时目录，
# 避免测试写入用户真实的数据目录
_tmp = tempfile.mkdtemp(prefix="bilibili_downloader_test_")
os.chdir(_tmp)
os.environ["DRIVER"] = "~none"
os.environ["LOCALSTORE_BASE_DIR"] = _tmp
os.environ["LOCALSTORE_DATA_DIR"] = str(Path(_tmp) / "data")
os.environ["LOCALSTORE_CONFIG_DIR"] = str(Path(_tmp) / "config")
os.environ["LOCALSTORE_CACHE_DIR"] = str(Path(_tmp) / "cache")

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OnebotV11Adapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OnebotV11Adapter)
nonebot.load_plugin("nonebot_plugin_bilibili_downloader")
