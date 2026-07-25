import os

# 找到最新的HTML文件
html_dir = r'd:\CodeSpace\Odin-Assistant\output\html\2026-07-15'
files = sorted(os.listdir(html_dir))
print("今日HTML文件:", files)

# 读取最新的
latest_html = os.path.join(html_dir, files[-1])
content = open(latest_html, 'r', encoding='utf-8').read()

# 查找RSS部分
idx = content.find('RSS 订阅更新')
if idx >= 0:
    print(f"\n=== RSS 订阅更新 找到于位置 {idx} ===")
    print(content[idx:idx+3000])
else:
    print("\n未找到 'RSS 订阅更新' 文本")
    # 搜索其他关键词
    for kw in ['RSS', 'feed-group', 'rss-item', '订阅']:
        idx = content.find(kw)
        if idx >= 0:
            print(f"'{kw}' 在位置 {idx}")
    # 查看header info中的RSS统计
    idx = content.find('RSS 源')
    if idx >= 0:
        print(f"\nRSS 源信息: {content[idx-50:idx+100]}")
    # 查看section-count
    import re
    for m in re.finditer(r'rss-section-count[^<]*', content):
        print(f"\nRSS count: {m.group()}")

# 也检查daily.html
daily = r'd:\CodeSpace\Odin-Assistant\output\html\latest\daily.html'
if os.path.exists(daily):
    d_content = open(daily, 'r', encoding='utf-8').read()
    didx = d_content.find('RSS 订阅更新')
    if didx >= 0:
        print(f"\n=== daily.html 中的 RSS 订阅更新 (位置 {didx}) ===")
        print(d_content[didx:didx+2000])
    else:
        print("\ndaily.html 中无 RSS 订阅更新")
