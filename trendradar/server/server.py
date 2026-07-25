# coding=utf-8
"""
Odin-Assistant Web 服务器

提供本地 HTTP 服务，用于通过浏览器（手机/电脑）访问生成的 HTML 报告。
支持：
  - 本地局域网访问
  - 通过 ngrok 隧道实现外网访问
  - 自动生成报告索引页面
"""

import argparse
import io
import json
import mimetypes
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional


# 项目根目录（自动检测）
def _find_project_root() -> Path:
    """从当前文件位置向上查找项目根目录"""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "output").is_dir() and (parent / "trendradar").is_dir():
            return parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()
OUTPUT_DIR = PROJECT_ROOT / "output"
HTML_DIR = OUTPUT_DIR / "html"


def get_local_ip() -> str:
    """获取本机局域网 IP 地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        # 不需要真正连接
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_available_port(start: int = 8080, end: int = 9090) -> int:
    """查找可用的端口号"""
    for port in range(start, end):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", port))
                return port
        except OSError:
            continue
    return start  # 如果都不可用，返回起始端口


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.1f} MB"


def collect_html_files() -> list:
    """收集 output/html/ 下的所有 HTML 文件，按日期分组"""
    entries = []
    html_root = HTML_DIR
    if not html_root.is_dir():
        return entries

    for item in sorted(html_root.iterdir(), reverse=True):
        if item.is_dir():
            # 日期目录（如 2026-07-11）
            date_str = item.name
            files = []
            for f in sorted(item.iterdir(), reverse=True):
                if f.suffix.lower() == ".html":
                    stat = f.stat()
                    files.append({
                        "name": f.name,
                        "path": f.relative_to(PROJECT_ROOT).as_posix(),
                        "size": format_file_size(stat.st_size),
                        "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%H:%M:%S"),
                    })
            if files:
                entries.append({
                    "type": "date_dir",
                    "date": date_str,
                    "files": files,
                })
        elif item.suffix.lower() == ".html":
            # 根目录下的 HTML 文件（如 index.html）
            stat = item.stat()
            entries.append({
                "type": "file",
                "name": item.name,
                "path": item.relative_to(PROJECT_ROOT).as_posix(),
                "size": format_file_size(stat.st_size),
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })

    return entries


def build_index_html(server_url: str) -> str:
    """生成美观的索引页面 HTML"""
    entries = collect_html_files()

    files_html = ""
    if not entries:
        files_html = """
            <div class="empty-state">
                <div class="empty-icon">📂</div>
                <h3>暂无报告</h3>
                <p>请先运行 <code>python -m trendradar</code> 生成报告</p>
            </div>
        """
    else:
        for entry in entries:
            if entry["type"] == "date_dir":
                # 日期分组
                files_html += f"""
                    <div class="date-group">
                        <div class="date-header">
                            <span class="date-label">📅 {entry["date"]}</span>
                            <span class="file-count">{len(entry["files"])} 个文件</span>
                        </div>
                        <div class="file-list">
                """
                for f in entry["files"]:
                    files_html += f"""
                            <a href="/{f['path']}" class="file-item" target="_blank">
                                <span class="file-icon">📄</span>
                                <span class="file-name">{f['name']}</span>
                                <span class="file-meta">{f['size']} · {f['mtime']}</span>
                            </a>
                    """
                files_html += """
                        </div>
                    </div>
                """
            else:
                # 单个文件
                files_html += f"""
                    <a href="/{entry['path']}" class="file-item" target="_blank">
                        <span class="file-icon">📄</span>
                        <span class="file-name">{entry['name']}</span>
                        <span class="file-meta">{entry['size']} · {entry['mtime']}</span>
                    </a>
                """

    ip = get_local_ip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Odin-Assistant 报告浏览</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            background: #f0f2f5;
            color: #333;
            min-height: 100vh;
        }}
        .header {{
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
            color: white;
            padding: 32px 20px 24px;
            text-align: center;
        }}
        .header h1 {{
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 4px;
        }}
        .header p {{
            font-size: 14px;
            opacity: 0.85;
        }}
        .access-info {{
            background: white;
            margin: 16px;
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        .access-info h3 {{
            font-size: 14px;
            color: #666;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .access-url {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 14px;
            background: #f5f3ff;
            border: 1px solid #e0d7fc;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            color: #4f46e5;
            word-break: break-all;
            margin-bottom: 8px;
        }}
        .access-url .label {{
            font-size: 12px;
            color: #888;
            font-weight: 400;
            flex-shrink: 0;
        }}
        .access-url .copy-btn {{
            margin-left: auto;
            flex-shrink: 0;
            background: #4f46e5;
            color: white;
            border: none;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 12px;
            cursor: pointer;
        }}
        .access-url .copy-btn:hover {{
            background: #4338ca;
        }}
        .access-tip {{
            font-size: 12px;
            color: #999;
            margin-top: 8px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 680px;
            margin: 0 auto;
            padding: 0 16px 32px;
        }}
        .section-title {{
            font-size: 16px;
            font-weight: 600;
            color: #555;
            margin: 20px 0 12px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .date-group {{
            margin-bottom: 16px;
        }}
        .date-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            background: white;
            border-radius: 8px 8px 0 0;
            border-bottom: 1px solid #f0f0f0;
            font-size: 14px;
        }}
        .date-label {{
            font-weight: 600;
            color: #444;
        }}
        .file-count {{
            font-size: 12px;
            color: #999;
        }}
        .file-list {{
            background: white;
            border-radius: 0 0 8px 8px;
            overflow: hidden;
        }}
        .file-item {{
            display: flex;
            align-items: center;
            padding: 12px 14px;
            text-decoration: none;
            color: #333;
            border-bottom: 1px solid #f5f5f5;
            transition: background 0.15s;
            gap: 10px;
        }}
        .file-item:last-child {{
            border-bottom: none;
        }}
        .file-item:hover {{
            background: #f9f9ff;
        }}
        .file-item:active {{
            background: #f0eeff;
        }}
        .file-icon {{
            font-size: 18px;
            flex-shrink: 0;
        }}
        .file-name {{
            flex: 1;
            font-size: 14px;
            font-weight: 500;
        }}
        .file-meta {{
            font-size: 12px;
            color: #aaa;
            flex-shrink: 0;
        }}
        .empty-state {{
            text-align: center;
            padding: 60px 20px;
            background: white;
            border-radius: 12px;
        }}
        .empty-icon {{
            font-size: 48px;
            margin-bottom: 12px;
        }}
        .empty-state h3 {{
            font-size: 18px;
            color: #666;
            margin-bottom: 8px;
        }}
        .empty-state p {{
            font-size: 14px;
            color: #999;
        }}
        .empty-state code {{
            background: #f5f5f5;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 13px;
        }}
        .footer {{
            text-align: center;
            padding: 24px;
            font-size: 12px;
            color: #bbb;
        }}
        @media (max-width: 480px) {{
            .header {{ padding: 24px 16px 20px; }}
            .header h1 {{ font-size: 20px; }}
            .access-info {{ margin: 12px; }}
            .container {{ padding: 0 12px 24px; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 Odin-Assistant</h1>
        <p>热点新闻报告浏览器</p>
    </div>

    <div class="access-info">
        <h3>🌐 访问地址</h3>
        <div class="access-url">
            <span class="label">本机:</span>
            <span>http://localhost:{server_url.split(':')[-1]}/</span>
        </div>
        <div class="access-url" id="lan-url">
            <span class="label">局域网:</span>
            <span>http://{ip}:{server_url.split(':')[-1]}/</span>
            <button class="copy-btn" onclick="copyText('http://{ip}:{server_url.split(':')[-1]}/')">复制</button>
        </div>
        <div class="access-tip">
            💡 手机访问：确保手机与电脑在同一 WiFi 下，在手机浏览器中打开上方 <strong>局域网</strong> 地址
        </div>
    </div>

    <div class="container">
        <div class="section-title">📊 报告列表</div>
        {files_html}
    </div>

    <div class="footer">
        Odin-Assistant v6.10.0 · 生成于 {now}
    </div>

    <script>
        function copyText(text) {{
            if (navigator.clipboard) {{
                navigator.clipboard.writeText(text).then(function() {{
                    var btn = event.target;
                    var orig = btn.textContent;
                    btn.textContent = '✓ 已复制';
                    setTimeout(function() {{ btn.textContent = orig; }}, 2000);
                }});
            }} else {{
                var ta = document.createElement('textarea');
                ta.value = text;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                alert('已复制到剪贴板');
            }}
        }}
    </script>
</body>
</html>"""


class OdinAssistantHandler(SimpleHTTPRequestHandler):
    """自定义 HTTP 请求处理器"""

    def __init__(self, *args, **kwargs):
        # 设置根目录为项目根目录
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 根路径 -> 显示索引页
        if path == "/" or path == "":
            self._serve_index()
            return

        # API: 获取服务器信息
        if path == "/api/info":
            self._serve_info()
            return

        # API: 列出 HTML 文件
        if path == "/api/files":
            self._serve_file_list()
            return

        # 默认：提供静态文件服务
        return super().do_GET()

    def _serve_index(self):
        """提供索引页面"""
        server_url = f"http://localhost:{self.server.server_port}"
        html = build_index_html(server_url)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_info(self):
        """提供服务器信息 JSON"""
        info = {
            "status": "running",
            "version": "6.10.0",
            "project": "Odin-Assistant",
            "local_ip": get_local_ip(),
            "port": self.server.server_port,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        data = json.dumps(info, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _serve_file_list(self):
        """提供文件列表 JSON"""
        entries = collect_html_files()
        data = json.dumps(entries, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        """自定义日志格式"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"  [{timestamp}] {self.address_string()} - {format % args}")


def find_ngrok() -> Optional[str]:
    """查找 ngrok 可执行文件"""
    # 检查常见位置
    common_paths = [
        PROJECT_ROOT / "ngrok.exe",
        PROJECT_ROOT / "ngrok",
        Path.home() / "ngrok.exe",
        Path.home() / "ngrok",
        Path.home() / "scoop" / "shims" / "ngrok.exe",
        Path.home() / "scoop" / "shims" / "ngrok",
        Path.home() / "AppData" / "Local" / "ngrok" / "ngrok.exe",
    ]

    for p in common_paths:
        if p.is_file():
            return str(p)

    # 检查 PATH
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["where", "ngrok"], capture_output=True, text=True, timeout=3
            )
        else:
            result = subprocess.run(
                ["which", "ngrok"], capture_output=True, text=True, timeout=3
            )
        if result.returncode == 0:
            path = result.stdout.strip().split("\n")[0].strip()
            if path:
                return path
    except Exception:
        pass

    return None


def find_cloudflared() -> Optional[str]:
    """查找 cloudflared 可执行文件"""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["where", "cloudflared"], capture_output=True, text=True, timeout=3
            )
        else:
            result = subprocess.run(
                ["which", "cloudflared"], capture_output=True, text=True, timeout=3
            )
        if result.returncode == 0:
            path = result.stdout.strip().split("\n")[0].strip()
            if path:
                return path
    except Exception:
        pass
    return None


def _configure_ngrok_token(ngrok_path: str) -> bool:
    """从环境变量 NGROK_TOKEN 配置 ngrok 认证令牌"""
    token = os.environ.get("NGROK_TOKEN", "").strip()
    if not token:
        return False

    print(f"  🔑 检测到 NGROK_TOKEN 环境变量，正在配置 ngrok 认证...")
    try:
        result = subprocess.run(
            [ngrok_path, "config", "add-authtoken", token],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            print(f"  ✅ ngrok 认证配置成功")
            return True
        else:
            print(f"  ⚠️  ngrok 认证配置失败: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  ⚠️  ngrok 认证配置出错: {e}")
        return False


def start_ngrok_tunnel(port: int) -> Optional[threading.Thread]:
    """启动 ngrok 隧道"""
    ngrok_path = find_ngrok()
    if not ngrok_path:
        print("  ⚠️  未找到 ngrok，请先安装 ngrok (https://ngrok.com/download)")
        print("     或使用 --cloudflared 参数使用 Cloudflare Tunnel")
        return None

    # 自动从环境变量配置 ngrok token
    _configure_ngrok_token(ngrok_path)

    print(f"  🚇 正在启动 ngrok 隧道...")

    def run_ngrok():
        try:
            proc = subprocess.run(
                [ngrok_path, "http", str(port), "--log", "stdout"],
                capture_output=True, text=True, timeout=10
            )
        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            print(f"  ❌ ngrok 启动失败: {e}")

    thread = threading.Thread(target=run_ngrok, daemon=True)
    thread.start()

    # 等待 ngrok 启动并获取公网地址
    time.sleep(3)

    # 通过 ngrok API 获取公网地址
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=5)
        data = json.loads(resp.read().decode())
        for tunnel in data.get("tunnels", []):
            if tunnel.get("public_url"):
                public_url = tunnel["public_url"]
                print(f"  ✅ ngrok 隧道已创建!")
                print(f"  🌐 外网地址: \033[1;36m{public_url}\033[0m")
                print(f"  📱 手机访问此地址即可查看报告")
                print(f"  ⚠️  免费版 ngrok 每次启动地址会变，如需固定地址请升级付费版")
                return thread
    except Exception:
        pass

    print("  ⚠️  ngrok 正在启动中，请稍后访问 http://127.0.0.1:4040 查看状态")
    return thread


def start_cloudflared_tunnel(port: int) -> Optional[subprocess.Popen]:
    """启动 Cloudflare Tunnel (cloudflared)"""
    cf_path = find_cloudflared()
    if not cf_path:
        print("  ⚠️  未找到 cloudflared，请先安装:")
        print("     Windows: scoop install cloudflared")
        print("     macOS:   brew install cloudflared")
        print("     Linux:   apt install cloudflared")
        return None

    print(f"  🚇 正在启动 Cloudflare Tunnel...")
    print(f"  ⚠️  首次使用请先执行: cloudflared tunnel login")

    try:
        proc = subprocess.Popen(
            [cf_path, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # 等待并提取公网地址
        def monitor_output():
            url_found = False
            for line in proc.stdout:
                print(f"  {line.strip()}")
                if "https://" in line and ".trycloudflare.com" in line and not url_found:
                    for word in line.split():
                        if "https://" in word and ".trycloudflare.com" in word:
                            url = word.strip()
                            print(f"\n  ✅ Cloudflare Tunnel 已创建!")
                            print(f"  🌐 外网地址: \033[1;36m{url}\033[0m")
                            print(f"  📱 手机访问此地址即可查看报告\n")
                            url_found = True

        thread = threading.Thread(target=monitor_output, daemon=True)
        thread.start()
        return proc

    except Exception as e:
        print(f"  ❌ Cloudflare Tunnel 启动失败: {e}")
        return None


def run_server(
    host: str = "0.0.0.0",
    port: int = 0,
    tunnel: str = "",
    open_browser: bool = False,
):
    """
    启动 Odin-Assistant HTTP 服务器

    Args:
        host: 监听地址 (默认 0.0.0.0 表示监听所有网络接口)
        port: 端口号 (0=自动选择)
        tunnel: 隧道类型 ("ngrok", "cloudflared", "" 表示不启动)
        open_browser: 是否自动打开浏览器
    """
    if port == 0:
        port = get_available_port()

    server = HTTPServer((host, port), OdinAssistantHandler)
    local_ip = get_local_ip()

    print()
    print("  ╔═══════════════════════════════════════════╗")
    print("  ║       Odin-Assistant 报告服务器               ║")
    print("  ╚═══════════════════════════════════════════╝")
    print()
    print(f"  📍 本机访问:  http://localhost:{port}/")
    print(f"  📍 局域网访问: http://{local_ip}:{port}/")
    print()
    print(f"  📂 服务目录: {OUTPUT_DIR}")
    print()
    print(f"  💡 局域网访问说明:")
    print(f"     1. 确保手机/其他设备与电脑连接同一 WiFi")
    print(f"     2. 在手机浏览器打开上方「局域网访问」地址")
    print(f"     3. 如无法访问，请检查防火墙设置")
    print()
    print(f"  ⌨️  按 Ctrl+C 停止服务器")
    print()

    # 启动隧道
    tunnel_proc = None
    if tunnel == "ngrok":
        start_ngrok_tunnel(port)
    elif tunnel == "cloudflared":
        tunnel_proc = start_cloudflared_tunnel(port)

    # 自动打开浏览器
    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}/")

    try:
        print(f"  🟢 服务器已启动，等待请求...")
        print()
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("  🛑 正在停止服务器...")
        server.shutdown()
        if tunnel_proc:
            tunnel_proc.terminate()
        print("  ✅ 服务器已停止")
        print()


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="Odin-Assistant 报告服务器 - 通过浏览器访问生成的 HTML 报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="监听地址 (默认: 0.0.0.0，监听所有网络接口)"
    )
    parser.add_argument(
        "--port", type=int, default=0,
        help="端口号 (默认: 0=自动选择)"
    )
    parser.add_argument(
        "--tunnel", choices=["ngrok", "cloudflared", ""], default="",
        help="创建外网隧道以便通过互联网访问 (需提前安装对应工具)"
    )
    parser.add_argument(
        "--open", action="store_true",
        help="自动在浏览器中打开索引页面"
    )

    args = parser.parse_args()
    run_server(
        host=args.host,
        port=args.port,
        tunnel=args.tunnel,
        open_browser=args.open,
    )


if __name__ == "__main__":
    main()
