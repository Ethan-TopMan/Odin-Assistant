#!/usr/bin/env python3
"""
腾讯云 COS 上传工具 —— 将 HTML 报告上传到 COS 并开启公共读

用于 GitHub Actions 中替代 aliyunpan CLI，无需下载任何二进制文件。
依赖 `boto3`（已安装在 pyproject.toml 中）。

用法：
    python upload_to_cos.py <本地文件/目录> <bucket> <access_key> <secret_key> <endpoint> [region]

环境变量（备选，优先级低于命令行参数）：
    S3_BUCKET_NAME, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT_URL, S3_REGION

上传后访问地址：
    https://<bucket>.cos.<region>.myqcloud.com/index.html
"""

import os
import sys
import mimetypes

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError
except ImportError:
    print("❌ 需要 boto3，请安装: pip install boto3")
    sys.exit(1)


def get_config() -> dict:
    """获取配置：命令行参数优先，环境变量备选"""
    if len(sys.argv) >= 6:
        return {
            "local_path": sys.argv[1],
            "bucket_name": sys.argv[2],
            "access_key_id": sys.argv[3],
            "secret_access_key": sys.argv[4],
            "endpoint_url": sys.argv[5],
            "region": sys.argv[6] if len(sys.argv) > 6 else "",
        }
    # 从环境变量读取
    return {
        "local_path": sys.argv[1] if len(sys.argv) > 1 else "index.html",
        "bucket_name": os.environ.get("S3_BUCKET_NAME", ""),
        "access_key_id": os.environ.get("S3_ACCESS_KEY_ID", ""),
        "secret_access_key": os.environ.get("S3_SECRET_ACCESS_KEY", ""),
        "endpoint_url": os.environ.get("S3_ENDPOINT_URL", ""),
        "region": os.environ.get("S3_REGION", ""),
    }


def normalize_endpoint(endpoint: str, bucket: str) -> str:
    """修复 endpoint 格式：
    - 如果 endpoint 中包含了 bucket 名（例如 xxx.cos.region.myqcloud.com），
      则去掉 bucket 前缀，只保留 cos.region.myqcloud.com
    - 检测是否误用了 cos-website 域名（只读），提醒用户修正
    """
    if not endpoint:
        return endpoint

    import re

    # 检测是否用了 cos-website 域名
    if "cos-website" in endpoint:
        print(f"  ❌ 检测到 endpoint 使用了 cos-website 域名！")
        print(f"     cos-website 是静态网站域名，只支持读取，不支持上传")
        print(f"     请修改 GitHub Secret: S3_ENDPOINT_URL")
        print(f"     当前值: {endpoint}")
        # 尝试自动修正: cos-website → cos
        corrected = endpoint.replace("cos-website", "cos")
        if corrected != endpoint:
            print(f"     已自动修正为: {corrected}")
            print(f"     (但仍建议去 GitHub Secrets 中更新)")
            return corrected
        return endpoint

    # 如果 endpoint 以 bucket 开头（如 https://trendradar-xxx.cos.ap-guangzhou.myqcloud.com）
    pattern = re.compile(
        r"^(https?://)" + re.escape(bucket) + r"\.(.+)$", re.IGNORECASE
    )
    match = pattern.match(endpoint)
    if match:
        corrected = match.group(1) + match.group(2)
        print(f"  ⚠️  Endpoint 中包含了 bucket 名称，已自动修正为: {corrected}")
        print(f"     (建议去 GitHub Secrets 中更新 S3_ENDPOINT_URL)")
        return corrected
    return endpoint


def guess_content_type(file_path: str) -> str:
    """根据文件扩展名推断 Content-Type"""
    content_type, _ = mimetypes.guess_type(file_path)
    if content_type:
        return content_type
    if file_path.endswith(".html"):
        return "text/html; charset=utf-8"
    if file_path.endswith(".json"):
        return "application/json; charset=utf-8"
    if file_path.endswith(".txt"):
        return "text/plain; charset=utf-8"
    if file_path.endswith(".sqlite") or file_path.endswith(".db"):
        return "application/octet-stream"
    return "application/octet-stream"


def upload_file(s3_client, bucket: str, local_path: str, remote_key: str) -> bool:
    """上传单个文件"""
    if not os.path.isfile(local_path):
        print(f"  ❌ 文件不存在: {local_path}")
        return False

    content_type = guess_content_type(local_path)

    try:
        with open(local_path, "rb") as f:
            body = f.read()
        s3_client.put_object(
            Bucket=bucket,
            Key=remote_key,
            Body=body,
            ContentType=content_type,
        )
        print(f"  ✅ {local_path} → {remote_key} ({content_type})")
        return True
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        print(f"  ❌ 上传失败 [{error_code}] {error_msg}")
        if error_code == "MethodNotAllowed":
            print(f"  💡 提示: 使用了只读域名（如 cos-website），不支持上传")
            print(f"     正确示例: https://cos.ap-guangzhou.myqcloud.com")
            print(f"     请修改 GitHub Secret: S3_ENDPOINT_URL")
        return False


# 上传目录时跳过的文件后缀（大文件由 S3 远程存储后端处理，无需重复上传）
SKIP_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}


def upload_directory(s3_client, bucket: str, local_dir: str, remote_prefix: str):
    """递归上传目录（跳过数据库文件）"""
    if not os.path.isdir(local_dir):
        print(f"❌ 目录不存在: {local_dir}")
        return False

    success = True
    local_dir = os.path.normpath(local_dir)
    for root, dirs, files in os.walk(local_dir):
        for file in files:
            local_file = os.path.join(root, file)
            ext = os.path.splitext(file)[1].lower()

            # 跳过数据库文件（大文件，已由 S3 远程存储处理）
            if ext in SKIP_EXTENSIONS:
                continue
            remote_key = f"{remote_prefix}/{rel_path}".replace("\\", "/")
            if not upload_file(s3_client, bucket, local_file, remote_key):
                success = False
    return success


def main():
    config = get_config()

    local_path = config["local_path"]
    bucket = config["bucket_name"]
    access_key = config["access_key_id"]
    secret_key = config["secret_access_key"]
    endpoint = config["endpoint_url"]
    region = config["region"]

    # ── 进入流程 ──
    print("═══════════════════════════════════════════")
    print("  📤 腾讯云 COS 上传流程")
    print("═══════════════════════════════════════════")
    print(f"  路径: {local_path}")

    # 校验必填项
    missing = []
    if not bucket:
        missing.append("bucket_name / S3_BUCKET_NAME")
    if not access_key:
        missing.append("access_key_id / S3_ACCESS_KEY_ID")
    if not secret_key:
        missing.append("secret_access_key / S3_SECRET_ACCESS_KEY")
    if not endpoint:
        missing.append("endpoint_url / S3_ENDPOINT_URL")
    if missing:
        print(f"  ❌ 缺少必要配置: {', '.join(missing)}")
        print("用法: python upload_to_cos.py <本地路径> <bucket> <access_key> <secret_key> <endpoint> [region]")
        print("或设置环境变量: S3_BUCKET_NAME, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT_URL")
        sys.exit(1)

    if not os.path.exists(local_path):
        print(f"  ❌ 路径不存在: {local_path}")
        sys.exit(1)

    # 自动修正 endpoint（去掉可能嵌入的 bucket 名）
    endpoint = normalize_endpoint(endpoint, bucket)

    print(f"  ✅ 配置检查通过")
    print(f"  🌐 存储桶: {bucket}")
    print(f"  🔗 Endpoint: {endpoint}")
    if region:
        print(f"  📍 Region: {region}")
    print(f"  ─────────────────────────────────────────")

    # 创建 S3 客户端（使用 path 风格以兼容 COS）
    boto_config = BotoConfig(
        signature_version="s3v4",
        connect_timeout=10,
        read_timeout=60,
        retries={"max_attempts": 3},
        s3={"addressing_style": "virtual"},
    )
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint,
        region_name=region or "ap-guangzhou",
        config=boto_config,
    )

    # 上传
    if os.path.isfile(local_path):
        file_name = os.path.basename(local_path)
        success = upload_file(s3_client, bucket, local_path, file_name)
    else:
        dir_name = os.path.basename(os.path.normpath(local_path))
        success = upload_directory(s3_client, bucket, local_path, dir_name)

    if success:
        # 打印访问地址
        bucket_domain = endpoint.replace("https://", "").replace("http://", "")
        if region:
            access_url = f"https://{bucket}.cos.{region}.myqcloud.com"
        else:
            access_url = f"https://{bucket}.{bucket_domain}"
        print(f"  ─────────────────────────────────────────")
        print(f"  ✅ 上传完成！")
        print(f"  📱 手机访问地址:")
        print(f"     {access_url}/index.html")
        print("═══════════════════════════════════════════")
    else:
        print(f"  ─────────────────────────────────────────")
        print(f"  ❌ COS 上传失败！部分文件上传出错")
        print("═══════════════════════════════════════════")
        sys.exit(1)


if __name__ == "__main__":
    main()
