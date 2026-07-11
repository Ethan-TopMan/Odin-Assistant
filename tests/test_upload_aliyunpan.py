"""测试阿里云盘上传脚本的辅助函数"""
import json
import sys
import os
from unittest.mock import Mock, patch

# 添加脚本目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.upload_to_aliyunpan import (
    get_access_token,
    get_file_drive_id,
    create_folder,
    get_path_file_id,
    upload_file,
    upload_directory,
)


class TestGetAccessToken:
    """测试获取 access_token"""

    def test_success(self):
        """正常获取 token"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "test_access_token_123",
            "drive_id": "test_drive_456",
            "token_type": "Bearer",
            "expires_in": 7200,
        }
        mock_response.status_code = 200

        with patch("scripts.upload_to_aliyunpan.requests.post",
                   return_value=mock_response) as mock_post:
            token, drive_id = get_access_token("test_refresh_token")

            assert token == "test_access_token_123"
            assert drive_id == "test_drive_456"
            mock_post.assert_called_once_with(
                "https://openapi.alipan.com/oauth/access_token",
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": "test_refresh_token",
                    "client_id": "cf9f70e8fc61430f8ec5ab5cadf31375",
                },
                timeout=30,
            )
            print("✅ test_success 通过")

    def test_failure(self):
        """token 无效"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": "InvalidParameter",
            "message": "refresh_token is invalid",
        }
        mock_response.status_code = 400

        with patch("scripts.upload_to_aliyunpan.requests.post",
                   return_value=mock_response):
            token, drive_id = get_access_token("bad_token")
            assert token is None
            assert drive_id is None
            print("✅ test_failure 通过")


class TestGetFileDriveId:
    """测试获取 drive_id"""

    def test_success(self):
        mock_response = Mock()
        mock_response.json.return_value = {
            "default_drive_id": "backup_drive_789",
            "resource_drive_id": "resource_drive_000",
        }

        with patch("scripts.upload_to_aliyunpan.requests.post",
                   return_value=mock_response) as mock_post:
            drive_id = get_file_drive_id("test_token")
            assert drive_id == "backup_drive_789"
            mock_post.assert_called_once()
            print("✅ test_get_file_drive_id 通过")


class TestCreateFolder:
    """测试创建文件夹"""

    def test_create_in_root(self):
        mock_response = Mock()
        mock_response.json.return_value = {"file_id": "new_folder_id_123"}

        with patch("scripts.upload_to_aliyunpan.requests.post",
                   return_value=mock_response) as mock_post:
            file_id = create_folder("token", "drive123", "/", "TestFolder")
            assert file_id == "new_folder_id_123"
            # 检查请求体
            call_kwargs = mock_post.call_args[1]["json"]
            assert call_kwargs["parent_file_id"] == "root"
            assert call_kwargs["name"] == "TestFolder"
            assert call_kwargs["type"] == "folder"
            print("✅ test_create_in_root 通过")


class TestUploadFile:
    """测试上传文件流程"""

    def test_rapid_upload(self):
        """秒传场景"""
        mock_create = Mock()
        mock_create.json.return_value = {
            "file_id": "file_123",
            "rapid_upload": True,
            "upload_id": "",
            "part_info_list": [],
        }
        mock_create.status_code = 200

        with patch("scripts.upload_to_aliyunpan.requests.post",
                   return_value=mock_create), \
             patch("scripts.upload_to_aliyunpan.os.path.getsize",
                   return_value=1024):
            # 用临时文件测试
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
                f.write(b"<html>test</html>")
                tmp_path = f.name

            try:
                result = upload_file("token", "drive123", tmp_path, "/TrendRadar")
                # 至少不会崩溃
                print(f"✅ test_rapid_upload 通过 (result={result})")
            finally:
                os.unlink(tmp_path)


def run_tests():
    """运行所有测试"""
    tests = [
        TestGetAccessToken(),
        TestGetFileDriveId(),
        TestCreateFolder(),
        TestUploadFile(),
    ]

    passed = 0
    failed = 0

    for test in tests:
        for attr_name in dir(test):
            if attr_name.startswith("test_"):
                method = getattr(test, attr_name)
                try:
                    method()
                    passed += 1
                except Exception as e:
                    print(f"❌ {test.__class__.__name__}.{attr_name} 失败: {e}")
                    import traceback
                    traceback.print_exc()
                    failed += 1

    print(f"\n{'='*40}")
    print(f"结果: {passed} 通过, {failed} 失败")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
