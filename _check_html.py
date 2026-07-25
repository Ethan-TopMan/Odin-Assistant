content = open(r'd:\CodeSpace\Odin-Assistant\output\html\latest\current.html', 'r', encoding='utf-8').read()

# 搜索 RSS 相关内容
keywords = ['RSS', 'rss', '订阅', 'feed', '时间线', '时间流', '热榜', '平台']
for kw in keywords:
    idx = content.find(kw)
    count = content.count(kw)
    print(f'"{kw}": 出现 {count} 次')
    if idx >= 0:
        start = max(0, idx - 100)
        end = min(len(content), idx + 200)
        snippet = content[start:end]
        print(f'  首次出现在位置 {idx}: ...{snippet}...')
    print()

# 看看整体结构
# 找关键词部分的结构
import re
# 找所有 section/div 的 class 或 id 
sections = re.findall(r'<div[^>]*class="[^"]*"[^>]*>', content)
for s in sections[:30]:
    print(s)
