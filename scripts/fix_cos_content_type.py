#!/usr/bin/env python3
"""修复 COS 中已有文件的 Content-Type（用于修复之前上传的错误元数据）"""

import os
import sys

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError
except ImportError:
    print("❌ 需要 boto3")
    sys.exit(1)


def fix_metadata():
    bucket = os.environ.get("S3_BUCKET_NAME", "")
    access_key = os.environ.get("S3_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("S3_SECRET_ACCESS_KEY", "")
    endpoint = os.environ.get("S3_ENDPOINT_URL", "")
    region = os.environ.get("S3_REGION", "")

    if not all([bucket, access_key, secret_key, endpoint]):
        print("❌ 请设置 S3_BUCKET_NAME, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT_URL")
        sys.exit(1)

    # 修正 endpoint
    if bucket and endpoint and bucket in endpoint:
        endpoint = endpoint.replace(f"https://{bucket}.", "https://")

    s3 = boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint,
        region_name=region or "ap-beijing",
        config=BotoConfig(signature_version="s3v4"),
    )

    # 列出所有文件
    resp = s3.list_objects_v2(Bucket=bucket)
    files = [obj["Key"] for obj in resp.get("Contents", [])]

    if not files:
        print("ℹ️  桶中没有文件")
        return

    fixed = 0
    for key in files:
        # 获取当前元数据
        head = s3.head_object(Bucket=bucket, Key=key)
        current_type = head.get("ContentType", "")

        # 判断期望的 Content-Type
        if key.endswith(".html"):
            expected = "text/html; charset=utf-8"
        elif key.endswith(".json"):
            expected = "application/json; charset=utf-8"
        elif key.endswith(".txt"):
            expected = "text/plain; charset=utf-8"
        else:
            expected = ""

        if not expected:
            print(f"  ⏭️  {key} — 跳过（无需修改）")
            continue

        if current_type == expected:
            print(f"  ✅ {key} — 已经是 {expected}")
            continue

        # 修复：复制到自身
        s3.copy_object(
            Bucket=bucket,
            Key=key,
            CopySource={"Bucket": bucket, "Key": key},
            ContentType=expected,
            MetadataDirective="REPLACE",
        )
        print(f"  🔧 {key}: {current_type} → {expected}")
        fixed += 1

    print(f"\n✅ 修复完成，共处理 {fixed} 个文件")


if __name__ == "__main__":
    fix_metadata()
