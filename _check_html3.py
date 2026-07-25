content = open(r'd:\CodeSpace\Odin-Assistant\output\html\latest\current.html', 'r', encoding='utf-8').read()

# 找到 RSS section 的HTML部分
idx = content.find('class="rss-section')
if idx >= 0:
    # 找到对应的结束标签
    section_start = content.rfind('<div', 0, idx)
    # 输出从 section 开始到文件末尾
    rss_html = content[section_start:]
    print(rss_html[:5000])
    print("\n\n... (中间省略) ...\n\n")
    # 看看 feed-group 完整内容
    fg_start = rss_html.find('feed-group')
    if fg_start >= 0:
        # 找到对应的结束 div
        print(rss_html[fg_start-50:fg_start+2000])
