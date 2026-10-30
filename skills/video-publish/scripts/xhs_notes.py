"""小红书笔记管理：列出笔记，或者按完整标题删除一篇笔记（已发布的和定时未发的都在列表里）。

在 social-auto-upload 的虚拟环境里运行（cwd 是 social-auto-upload 的目录）：
    python xhs_notes.py <账号 cookie 文件> list
    python xhs_notes.py <账号 cookie 文件> delete "<完整标题>" [--confirm]
delete 不加 --confirm 时只打开删除确认框、核对框里写的是这篇笔记，然后点"取消"，什么都不删。
标题必须恰好匹配一篇笔记，否则不删。删除不能恢复，执行前要得到账号主人的同意。
"""
import asyncio
import sys

from patchright.async_api import async_playwright

NOTE_MANAGER = "https://creator.xiaohongshu.com/new/note-manager"

# 悬停后笔记卡片右上角出现一排操作图标，最右边的是删除（垃圾桶）；卡片左侧的图标（如视频的播放角标）不算。
TRASH_ICON = """(card) => {
  const box = card.getBoundingClientRect();
  const icons = [...card.querySelectorAll('svg')].filter(s => {
    const r = s.getBoundingClientRect();
    return r.width > 0 && r.top - box.top < 70 && r.left > box.left + box.width * 0.7;
  });
  if (icons.length < 3) return null;
  icons.sort((a, b) => b.getBoundingClientRect().left - a.getBoundingClientRect().left);
  const r = icons[0].getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}"""

# 删除确认框：从"无法恢复"那句提示往外找，直到找到写着指定文字的可见按钮，返回提示和按钮中心点。
DIALOG_BUTTON = """(label) => {
  const message = [...document.querySelectorAll('div')].find(e =>
    !e.children.length && e.innerText.includes('无法恢复') && e.getBoundingClientRect().height > 0);
  if (!message) return null;
  for (let box = message.parentElement; box; box = box.parentElement) {
    const button = [...box.querySelectorAll('*')].find(e =>
      e.innerText && e.innerText.trim() === label && e.getBoundingClientRect().height > 0 && !e.querySelector('*:not(span):not(div)'));
    if (button) {
      const r = button.getBoundingClientRect();
      return { message: message.innerText.trim(), x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }
  }
  return null;
}"""

NOTE_CARDS = """() => [...document.querySelectorAll('div')]
  .filter(e => e.querySelector('img') && /\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}/.test(e.innerText) && e.innerText.split('\\n').length < 14
               && ![...e.children].some(c => c.querySelector('img') && /\\d{4}-\\d{2}-\\d{2}/.test(c.innerText)))
  .map(e => e.innerText.split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 3).join(' | '))"""


async def open_manager(p, account):
    browser = await p.chromium.launch(headless=True, channel="chromium")
    context = await browser.new_context(storage_state=account, viewport={"width": 1400, "height": 1000})
    page = await context.new_page()
    await page.goto(NOTE_MANAGER)
    await page.wait_for_timeout(8000)
    return browser, page


async def list_notes(account):
    async with async_playwright() as p:
        browser, page = await open_manager(p, account)
        for line in await page.evaluate(NOTE_CARDS):
            print(line)
        await browser.close()


async def delete_note(account, title, confirm):
    async with async_playwright() as p:
        browser, page = await open_manager(p, account)
        title_el = page.get_by_text(title, exact=True)
        found = await title_el.count()
        if found != 1:
            sys.exit(f"标题为「{title}」的笔记有 {found} 篇，需要恰好 1 篇；没有删除")
        card = page.locator("div", has=title_el).filter(has=page.locator("img")).last
        point = None
        for _ in range(5):
            await card.hover()
            await page.wait_for_timeout(1200)
            point = await card.evaluate(TRASH_ICON)
            if point:
                break
        if not point:
            sys.exit("卡片上没有出现操作图标；没有删除")
        await page.mouse.click(point["x"], point["y"])
        await page.wait_for_timeout(2000)
        target = await page.evaluate(DIALOG_BUTTON, "确定" if confirm else "取消")
        if not target:
            sys.exit("没有出现删除确认框；没有删除")
        print("确认框：", target["message"])
        if title[:8] not in target["message"]:
            sys.exit("确认框里写的不是这篇笔记；没有删除")
        if not confirm:
            await page.mouse.click(target["x"], target["y"])
            print("只核对了确认框，已点取消，没有删除")
            await browser.close()
            return
        await page.mouse.click(target["x"], target["y"])
        await page.wait_for_timeout(4000)
        await page.reload()
        await page.wait_for_timeout(6000)
        left = await page.get_by_text(title, exact=True).count()
        print("已删除" if left == 0 else f"删除后仍有 {left} 篇同名笔记，请到创作平台核对")
        await browser.close()


if __name__ == "__main__":
    account_file, command = sys.argv[1], sys.argv[2]
    if command == "list":
        asyncio.run(list_notes(account_file))
    elif command == "delete":
        asyncio.run(delete_note(account_file, sys.argv[3], "--confirm" in sys.argv))
    else:
        sys.exit("用法：python xhs_notes.py <cookie 文件> list | delete \"<完整标题>\" [--confirm]")
