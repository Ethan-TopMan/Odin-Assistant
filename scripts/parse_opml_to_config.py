#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OPML文件解析器 - 将Feedly导出的OPML文件解析并追加到config.yaml的feeds部分

使用方法:
1. 将Feedly导出的.opml文件放在项目根目录或指定路径
2. 运行: python parse_opml_to_config.py your_file.opml
3. 脚本会自动将解析结果追加到config/config.yaml的feeds部分

要求:
- id, name, url 都需要用英文双引号包围
- 不能破坏config.yaml的其他模块结构
"""

import sys
import os
import re
import urllib.parse
from xml.etree import ElementTree as ET


def parse_opml_file(opml_file_path):
    """解析OPML文件，提取feed信息"""
    try:
        tree = ET.parse(opml_file_path)
        root = tree.getroot()
        feeds = []
        
        # 查找所有的outline元素
        for outline in root.findall('.//outline[@xmlUrl]'):
            xml_url = outline.get('xmlUrl', '').strip()
            title = (
                outline.get('title', '').strip() or 
                outline.get('text', '').strip()
            )
            
            if not xml_url:
                continue
                
            if not title:
                # 从URL中提取域名作为标题
                parsed = urllib.parse.urlparse(xml_url)
                if parsed.netloc:
                    title = parsed.netloc.replace('www.', '')
                else:
                    title = xml_url
            
            # 创建ID：清理标题字符串
            feed_id = re.sub(r'[^\w\s-]', '', title.lower())
            feed_id = re.sub(r'[-\s]+', '-', feed_id).strip('-')
            if not feed_id:
                feed_id = f"feed_{len(feeds) + 1}"
            
            feeds.append({
                'id': feed_id,
                'name': title,
                'url': xml_url
            })
            
        return feeds
        
    except Exception as e:
        print(f"❌ 解析OPML文件时发生错误: {e}")
        return []


def main():
    """主函数"""
    if len(sys.argv) != 2:
        print("❌ 使用方法: python parse_opml_to_config.py <opml_file_path>")
        print("   例如: python parse_opml_to_config.py feedly_export.opml")
        sys.exit(1)
    
    opml_file_path = sys.argv[1]
    
    if not os.path.exists(opml_file_path):
        print(f"❌ OPML文件不存在: {opml_file_path}")
        sys.exit(1)
    
    print(f"🔍 正在解析OPML文件: {opml_file_path}")
    feeds = parse_opml_file(opml_file_path)
    
    if not feeds:
        print("❌ 未从OPML文件中解析到任何feed")
        sys.exit(1)
    
    print(f"✅ 成功解析到 {len(feeds)} 个feed")
    
    # 读取config.yaml
    config_path = os.path.join('config', 'config.yaml')
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        sys.exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 简单方法：找到最后一个现有的feed条目，然后在其后添加
    lines = content.split('\n')
    feeds_start = -1
    feeds_end = -1
    
    # 找到feeds:行
    for i, line in enumerate(lines):
        if line.strip() == 'feeds:':
            feeds_start = i
            break
    
    if feeds_start == -1:
        print("❌ 未找到feeds配置部分")
        sys.exit(1)
    
    # 找到feeds部分的结束（下一个顶级配置项开始）
    feeds_end = len(lines)
    for i in range(feeds_start + 1, len(lines)):
        line = lines[i]
        # 检查是否是新的顶级配置项
        is_new_section = (
            line and 
            not line.startswith(' ') and 
            ':' in line and 
            not line.startswith('#')
        )
        if is_new_section:
            feeds_end = i
            break
    
    # 构建新的feeds内容
    new_feeds_lines = []
    for feed in feeds:
        new_feeds_lines.append(f'    - id: "{feed["id"]}"')
        new_feeds_lines.append(f'      name: "{feed["name"]}"')
        new_feeds_lines.append(f'      url: "{feed["url"]}"')
        new_feeds_lines.append('')  # 空行分隔
    
    # 组合新的内容
    updated_lines = (
        lines[:feeds_end] + 
        new_feeds_lines + 
        lines[feeds_end:]
    )
    
    updated_content = '\n'.join(updated_lines)
    
    # 备份原文件
    backup_path = config_path + '.backup'
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    # 写入更新后的配置
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(updated_content)
    
    print("\n🎉 操作完成!")
    print(f"✅ 已成功将 {len(feeds)} 个feed追加到config.yaml")
    print(f"✅ 原始配置已备份到: {backup_path}")


if __name__ == "__main__":
    main()