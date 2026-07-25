content = open(r'd:\CodeSpace\Odin-Assistant\output\html\latest\current.html', 'r', encoding='utf-8').read()

# 找到 rss-section 相关的内容
idx = content.find('rss-section')
if idx >= 0:
    print("=== RSS Section ===")
    print(content[idx:idx+2000])
else:
    print("未找到 rss-section")

# 也看看 feed-group 的内容
print("\n\n=== Feed Groups ===")
import re
feed_groups = list(re.finditer(r'<div class="feed-group[^"]*">', content))
print(f"找到 {len(feed_groups)} 个 feed-group")
for i, m in enumerate(feed_groups[:5]):
    start = m.start()
    end = min(len(content), start + 500)
    print(f"\n--- Feed Group {i+1} at {start} ---")
    print(content[start:end])

# 看看 header-info 中 RSS 的信息
idx2 = content.find('RSS 源')
if idx2 >= 0:
    print("\n\n=== RSS 源信息 ===")
    print(content[max(0,idx2-200):idx2+200])
