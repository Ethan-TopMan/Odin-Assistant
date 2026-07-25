content = open(r'd:\CodeSpace\Odin-Assistant\output\html\2026-07-15\23-07.html', 'r', encoding='utf-8').read()

# 直接搜索日期的RSS HTML部分
import re

# 找到 "rss-section" class 的 div 开始的 HTML
# 先找 class="rss-section"
matches = list(re.finditer(r'<div[^>]*class="[^"]*rss-section[^"]*"[^>]*>', content))
print(f"找到 {len(matches)} 个 rss-section div")
for m in matches:
    print(f"位置 {m.start()}: {m.group()}")

# 找 feed-group 的 div
matches2 = list(re.finditer(r'<div class="feed-group[^"]*">', content))
print(f"\n找到 {len(matches2)} 个 feed-group div")
for m in matches2:
    print(f"位置 {m.start()}: {m.group()}")

# 找 rss-item
matches3 = list(re.finditer(r'<div class="rss-item[^"]*">', content))
print(f"\n找到 {len(matches3)} 个 rss-item div")
for m in matches3[:5]:
    print(f"位置 {m.start()}: {m.group()}")
    start = m.start()
    end = min(len(content), start + 300)
    print(content[start:end])
    print("---")

# 检查 header-info 区域
idx = content.find('RSS 源')
if idx >= 0:
    print(f"\nRSS 源信息: {content[idx-100:idx+100]}")

idx = content.find('rss-section-count')
if idx >= 0:
    print(f"\nrss-section-count: {content[idx:idx+100]}")
