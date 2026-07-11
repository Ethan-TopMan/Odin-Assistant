#!/usr/bin/env python3
"""
阿里云盘上传工具（使用 Open API）
用法：
    python upload_to_aliyunpan.py <本地文件或目录路径> <refresh_token> [drive_id]
"""

import json
import os
import sys
import time
import requests


def get_access_token(refresh_token: str) -> tuple:
    """用 refresh_token 换取 access_token"""
    url = "https://openapi.alipan.com/oauth/access_token"
    resp = requests.post(url, json={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, timeout=30)
    data = resp.json()
    if "access_token" not in data:
        print(f"❌ 获取 access_token 失败: {data}")
        return None, None
    return data["access_token"], data.get("drive_id", "")


def get_file_drive_id(access_token: str) -> str:
    """获取默认的备份盘 drive_id"""
    url = "https://openapi.alipan.com/adrive/v1.0/user/getDriveInfo"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.post(url, headers=headers, timeout=30)
    data = resp.json()
    return data.get("default_drive_id", "")


def create_folder(access_token: str, drive_id: str, parent_path: str, folder_name: str) -> str:
    """创建文件夹，返回 file_id"""
    if parent_path == "/":
        parent_file_id = "root"
    else:
        parent_file_id = get_path_file_id(access_token, drive_id, parent_path)

    url = "https://openapi.alipan.com/adrive/v1.0/file/create"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.post(url, headers=headers, json={
        "drive_id": drive_id,
        "parent_file_id": parent_file_id,
        "name": folder_name,
        "type": "folder",
        "check_name_mode": "refuse",
    }, timeout=30)
    data = resp.json()
    return data.get("file_id", parent_file_id)


def get_path_file_id(access_token: str, drive_id: str, path: str) -> str:
    """根据路径获取 file_id（仅支持单层）"""
    if path == "/" or path == "":
        return "root"
    parts = path.strip("/").split("/", 1)
    current_id = "root"
    for part in parts:
        url = "https://openapi.alipan.com/adrive/v1.0/file/search"
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = requests.post(url, headers=headers, json={
            "drive_id": drive_id,
            "query": f"parent_file_id = '{current_id}' and name = '{part}' and type = 'folder'",
            "limit": 1,
        }, timeout=30)
        data = resp.json()
        items = data.get("items", [])
        if not items:
            # 创建文件夹
            current_id = create_folder(access_token, drive_id, path.rsplit(part, 1)[0], part)
        else:
            current_id = items[0]["file_id"]
    return current_id


def upload_file(access_token: str, drive_id: str, local_path: str, remote_dir: str):
    """上传单个文件"""
    file_name = os.path.basename(local_path)
    file_size = os.path.getsize(local_path)

    print(f"📄 上传: {file_name} ({file_size} bytes)")

    # 1. 创建文件（获取上传地址）
    url = "https://openapi.alipan.com/adrive/v1.0/file/create"
    headers = {"Authorization": f"Bearer {access_token}"}

    parent_file_id = get_path_file_id(access_token, drive_id, remote_dir)

    create_resp = requests.post(url, headers=headers, json={
        "drive_id": drive_id,
        "parent_file_id": parent_file_id,
        "name": file_name,
        "type": "file",
        "size": file_size,
        "check_name_mode": "overwrite",
    }, timeout=30)
    create_data = create_resp.json()

    if "file_id" not in create_data:
        print(f"❌ 创建文件失败: {create_data}")
        return False

    # 检查是否需要上传（可能已秒传）
    if create_data.get("rapid_upload", False):
        print(f"⚡ 秒传成功: {file_name}")
        return True

    # 2. 获取上传地址
    upload_url = None
    for part in create_data.get("part_info_list", []):
        upload_url = part.get("upload_url")
        break

    if not upload_url:
        print(f"❌ 获取上传地址失败")
        return False

    # 3. 上传文件内容
    with open(local_path, "rb") as f:
        file_data = f.read()

    put_resp = requests.put(upload_url, data=file_data, timeout=300)
    if put_resp.status_code not in (200, 201):
        print(f"❌ 上传文件内容失败: HTTP {put_resp.status_code}")
        return False

    # 4. 完成上传
    complete_url = "https://openapi.alipan.com/adrive/v1.0/file/complete"
    complete_resp = requests.post(complete_url, headers=headers, json={
        "drive_id": drive_id,
        "file_id": create_data["file_id"],
        "upload_id": create_data.get("upload_id", ""),
    }, timeout=30)

    if complete_resp.status_code == 200:
        print(f"✅ 上传成功: {file_name}")
        return True
    else:
        print(f"❌ 完成上传失败: {complete_resp.json()}")
        return False


def upload_directory(access_token: str, drive_id: str, local_dir: str, remote_dir: str):
    """上传整个目录"""
    if not os.path.isdir(local_dir):
        print(f"❌ 目录不存在: {local_dir}")
        return False

    success = True
    for root, dirs, files in os.walk(local_dir):
        # 计算相对路径
        rel_path = os.path.relpath(root, local_dir)
        if rel_path == ".":
            current_remote = remote_dir
        else:
            current_remote = f"{remote_dir}/{rel_path}".replace("\\", "/")

        for file in files:
            local_file = os.path.join(root, file)
            file_size = os.path.getsize(local_file)
            # 跳过空文件和过大文件（> 500MB）
            if file_size == 0:
                print(f"⏭️ 跳过空文件: {file}")
                continue
            if file_size > 500 * 1024 * 1024:
                print(f"⏭️ 跳过超大文件(>{'500MB'}): {file}")
                continue

            if not upload_file(access_token, drive_id, local_file, current_remote):
                success = False

    return success


def main():
    if len(sys.argv) < 3:
        print("用法: python upload_to_aliyunpan.py <本地路径> <refresh_token> [drive_id]")
        sys.exit(1)

    local_path = sys.argv[1]
    refresh_token = sys.argv[2]
    drive_id = sys.argv[3] if len(sys.argv) > 3 else ""

    if not os.path.exists(local_path):
        print(f"❌ 路径不存在: {local_path}")
        sys.exit(1)

    print("🔑 获取 access_token...")
    access_token, default_drive_id = get_access_token(refresh_token)
    if not access_token:
        print("❌ 登录失败，请检查 refresh_token")
        sys.exit(1)

    if not drive_id:
        drive_id = default_drive_id or get_file_drive_id(access_token)
    print(f"✅ 登录成功 (drive_id: {drive_id})")

    remote_dir = "/TrendRadar"
    print(f"📁 目标目录: {remote_dir}")

    if os.path.isfile(local_path):
        success = upload_file(access_token, drive_id, local_path, remote_dir)
    else:
        success = upload_directory(access_token, drive_id, local_path, remote_dir)

    if success:
        print("✅ 上传完成！请在阿里云盘 App 中查看 /TrendRadar 文件夹")
    else:
        print("⚠️ 部分文件上传失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
