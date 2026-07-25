# coding=utf-8
"""
Web 服务器模块 - 提供本地 HTTP 服务，支持外网访问

允许通过手机或其他设备远程访问 Odin-Assistant 生成的 HTML 报告。

使用方式:
  python -m trendradar serve            # 启动本地 HTTP 服务器
  python -m trendradar serve --tunnel   # 启动并创建外网隧道
  python -m trendradar serve --port 8080 --host 0.0.0.0
"""

from .server import run_server, get_local_ip

__all__ = ["run_server", "get_local_ip"]
