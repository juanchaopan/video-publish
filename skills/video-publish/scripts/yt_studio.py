"""YouTube Studio：列出视频，把草稿补全并定时或公开发布。

上传器传上去的视频停在草稿：必填的"是否为儿童内容"没有回答，"下一步"一直是灰的；标签藏在"展开"里没填上；
播放列表也没选。这里打开草稿逐项补全，走到"公开范围"这一步，按要求定时或公开。播放列表不存在时先新建（公开）。

用无头浏览器加普通 Chrome 的 User-Agent 打开 Studio（不带的话 Studio 会显示"浏览器不受支持"）；每次运行结束把
更新后的登录状态写回 cookie 文件，Google 会轮换会话 cookie，不写回的话登录很快失效。

在 social-auto-upload 的虚拟环境里运行（cwd 是 social-auto-upload 的目录）：
    python yt_studio.py <cookie 文件> list
    python yt_studio.py <cookie 文件> finish "<标题开头>" (--at "YYYY-MM-DD HH:MM" | --public)
                        [--tags "a,b"] [--playlist "<名称>"] [--kids] [--rehearse] [--shots <目录>]
标题开头要匹配一个草稿（同名草稿有多个时处理列表里的第一个）。--at 是本机时间。--kids 表示是儿童内容（默认不是）。
--rehearse 走到最后一步、截图，不点"定时/发布"，也不保存草稿的改动（但新建的播放列表会留下）。Studio 界面需要是英文。
"""
import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

from patchright.async_api import async_playwright

STUDIO = "https://studio.youtube.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"

# 页面上最后一个可见、文字正好等于指定内容的元素的中心点（弹窗总是加在页面最后，所以取最后一个）。
VISIBLE_TEXT = """(text) => {
  const hits = [...document.querySelectorAll('*')].filter(e =>
    !e.children.length && e.innerText && e.innerText.trim() === text && e.getBoundingClientRect().height > 0);
  if (!hits.length) return null;
  const r = hits[hits.length - 1].getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}"""

# 播放列表弹窗里名字等于指定文字的那一项：返回它的勾选框是否已勾上，以及勾选框的中心点；没有这一项返回 null。
PLAYLIST_ITEM = """(name) => {
  const label = [...document.querySelectorAll('tp-yt-paper-dialog *')].find(e =>
    !e.children.length && e.innerText && e.innerText.trim() === name && e.getBoundingClientRect().height > 0);
  if (!label) return null;
  for (let row = label.parentElement; row; row = row.parentElement) {
    const box = row.querySelector('[role=checkbox], ytcp-checkbox-lit');
    if (box) {
      const r = box.getBoundingClientRect();
      const checked = (box.getAttribute('aria-checked') || box.querySelector('[aria-checked]')?.getAttribute('aria-checked')) === 'true';
      return { checked, x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }
  }
  return null;
}"""

# "新建播放列表"弹窗：从标题文字往外找，直到同时包含可见的标题输入框和"Create"按钮，返回两者的中心点。
CREATE_DIALOG = """() => {
  const heading = [...document.querySelectorAll('*')].find(e =>
    !e.children.length && e.innerText && e.innerText.trim() === 'Create a new playlist' && e.getBoundingClientRect().height > 0);
  if (!heading) return null;
  const center = (e) => { const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };
  for (let box = heading.parentElement; box; box = box.parentElement) {
    const input = [...box.querySelectorAll('[contenteditable=true], textarea, input[type=text]')].find(e => e.getBoundingClientRect().height > 0);
    const button = [...box.querySelectorAll('button, ytcp-button')].find(e =>
      e.innerText && e.innerText.trim() === 'Create' && e.getBoundingClientRect().height > 0);
    if (input && button) return { input: center(input), button: center(button) };
  }
  return null;
}"""


def plain(text: str) -> str:
    """把 Studio 显示时间时用的窄不换行空格、不换行空格都当作普通空格，再合并连续空格。"""
    return " ".join(text.replace(" ", " ").replace(" ", " ").split())


class Studio:
    def __init__(self, page, shots: Path):
        self.page = page
        self.shots = shots

    async def shot(self, name: str) -> Path:
        self.shots.mkdir(parents=True, exist_ok=True)
        path = self.shots / f"youtube-{name}.png"
        await self.page.screenshot(path=str(path))
        return path

    async def step(self, name: str, action):
        try:
            await action()
        except Exception as exc:
            path = await self.shot(f"failed-{name}")
            raise RuntimeError(f"YouTube Studio 在「{name}」这一步失败，截图：{path}") from exc

    async def click_text(self, text: str):
        point = await self.page.evaluate(VISIBLE_TEXT, text)
        if point is None:
            raise RuntimeError(f"页面上没有可见的「{text}」")
        await self.page.mouse.click(point["x"], point["y"])

    async def open_videos(self):
        await self.page.goto(STUDIO, wait_until="domcontentloaded")
        await self.page.wait_for_timeout(5000)
        if "/channel/" not in self.page.url:
            sys.exit(f"没有进入频道（{self.page.url}）：登录可能失效，重新运行 sau youtube login --account <账号别名> --headed")
        channel = self.page.url.split("/channel/")[1].split("/")[0]
        await self.page.goto(f"{STUDIO}/channel/{channel}/videos/upload", wait_until="domcontentloaded")
        await self.page.locator("ytcp-video-row").first.wait_for(timeout=30000)
        await self.page.wait_for_timeout(2000)

    async def rows(self):
        return await self.page.evaluate(
            """() => [...document.querySelectorAll('ytcp-video-row')].map(r => {
                 const title = r.querySelector('#video-title')?.innerText.trim() || '';
                 const vis = r.querySelector('.tablecell-visibility')?.innerText.replace(/\\s+/g, ' ').trim() || '';
                 const date = r.querySelector('.tablecell-date')?.innerText.replace(/\\s+/g, ' ').trim() || '';
                 return { title, vis, date };
               })"""
        )

    async def finish(self, title: str, at: datetime | None, tags: list[str], playlist: str, kids: bool, rehearse: bool):
        page = self.page
        matches = [r for r in await self.rows() if r["title"].startswith(title)]
        drafts = [r for r in matches if "Draft" in r["vis"]]
        if not drafts:
            sys.exit(f"没有标题以「{title}」开头的草稿（匹配到：{matches}）")
        if len(drafts) > 1:
            print(f"有 {len(drafts)} 个同名草稿，处理列表里的第一个；其余的请到 Studio 删掉")

        async def open_draft():
            row = page.locator("ytcp-video-row").filter(has=page.locator("#video-title", has_text=title)).first
            await row.get_by_text("Edit draft").click()
            await page.locator("ytcp-uploads-dialog #next-button").wait_for(timeout=30000)
            await page.wait_for_timeout(2000)

        async def audience():
            name = "VIDEO_MADE_FOR_KIDS_MFK" if kids else "VIDEO_MADE_FOR_KIDS_NOT_MFK"
            await page.locator(f"tp-yt-paper-radio-button[name='{name}']").click()
            await page.wait_for_timeout(500)

        async def fill_tags():
            more = page.locator("ytcp-uploads-dialog #toggle-button").filter(has_text="Show more")
            if await more.count():
                await more.first.click()
                await page.wait_for_timeout(1000)
            box = page.locator("ytcp-uploads-dialog #tags-container input").first
            await box.scroll_into_view_if_needed()
            await box.click()
            await box.type(",".join(tags) + ",", delay=20)
            await page.wait_for_timeout(800)

        async def choose_playlist():
            dropdown = page.locator("ytcp-video-metadata-playlists ytcp-dropdown-trigger").first
            await dropdown.scroll_into_view_if_needed()
            await dropdown.click()
            await page.wait_for_timeout(1500)
            item = await page.evaluate(PLAYLIST_ITEM, playlist)
            if item is None:
                await page.get_by_role("button", name=re.compile(r"^(Create playlist|New playlist)$")).first.click()
                await page.wait_for_timeout(1000)
                await page.get_by_text("New playlist", exact=True).last.click()
                await page.wait_for_timeout(2000)
                dialog = await page.evaluate(CREATE_DIALOG)
                if dialog is None:
                    raise RuntimeError("没有出现新建播放列表的弹窗")
                await page.mouse.click(dialog["input"]["x"], dialog["input"]["y"])
                await page.keyboard.type(playlist, delay=20)
                await page.wait_for_timeout(500)
                await page.mouse.click(dialog["button"]["x"], dialog["button"]["y"])
                await page.wait_for_timeout(3000)
                item = await page.evaluate(PLAYLIST_ITEM, playlist)
                if item is None:
                    raise RuntimeError(f"新建的播放列表「{playlist}」没有出现在列表里")
            if not item["checked"]:
                await page.mouse.click(item["x"], item["y"])
                await page.wait_for_timeout(800)
            await self.click_text("Done")
            await page.wait_for_timeout(1000)

        async def to_visibility():
            for _ in range(3):
                await page.locator("ytcp-uploads-dialog #next-button").click()
                await page.wait_for_timeout(2000)
            await page.locator("#second-container-expand-button, tp-yt-paper-radio-button[name='PUBLIC']").first.wait_for(timeout=15000)

        async def set_visibility():
            if at is None:
                await page.locator("tp-yt-paper-radio-button[name='PUBLIC']").click()
                return
            await page.locator("#second-container-expand-button").click()
            await page.wait_for_timeout(1500)
            await page.locator("#datepicker-trigger").click()
            date_input = page.locator("ytcp-date-picker tp-yt-paper-input input").first
            await date_input.wait_for(timeout=8000)
            await date_input.fill(f"{at:%b} {at.day}, {at.year}")
            await date_input.press("Enter")
            await page.wait_for_timeout(1000)
            wanted_time = f"{at.hour % 12 or 12}:{at:%M} {'AM' if at.hour < 12 else 'PM'}"
            time_input = page.locator("#time-of-day-container input").first
            await time_input.click()
            await time_input.fill(wanted_time)
            await time_input.press("Enter")
            await page.wait_for_timeout(1000)
            shown_date = plain(await page.locator("#datepicker-trigger").inner_text())
            shown_time = plain(await time_input.input_value())
            if f"{at:%b} {at.day}" not in shown_date or shown_time != wanted_time:
                raise RuntimeError(f"定时没有填上：显示的是「{shown_date} {shown_time}」，想要的是「{at:%b} {at.day}, {at.year} {wanted_time}」")

        await self.step("打开草稿", open_draft)
        await self.step("儿童内容", audience)
        if tags:
            await self.step("标签", fill_tags)
        if playlist:
            await self.step("播放列表", choose_playlist)
        await self.step("走到公开范围", to_visibility)
        await self.step("公开范围", set_visibility)
        if rehearse:
            path = await self.shot("rehearsal")
            print(f"排练完成，没有保存。截图：{path}")
            return

        async def done():
            await page.locator("ytcp-uploads-dialog #done-button").click()
            await page.wait_for_timeout(4000)
            close = page.locator("ytcp-video-share-dialog #close-button, ytcp-uploads-still-processing-dialog #close-button")
            if await close.count():
                await close.first.click()
                await page.wait_for_timeout(1000)

        await self.step("确认", done)
        await self.open_videos()
        row = next((r for r in await self.rows() if r["title"].startswith(title)), None)
        print(f"完成：{row}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("account")
    parser.add_argument("command", choices=["list", "finish"])
    parser.add_argument("title", nargs="?")
    when = parser.add_mutually_exclusive_group()
    when.add_argument("--at")
    when.add_argument("--public", action="store_true")
    parser.add_argument("--tags", default="")
    parser.add_argument("--playlist", default="")
    parser.add_argument("--kids", action="store_true")
    parser.add_argument("--rehearse", action="store_true")
    parser.add_argument("--shots", default="publish-shots")
    args = parser.parse_args()
    if args.command == "finish" and (not args.title or not (args.at or args.public)):
        parser.error("finish 需要标题开头，以及 --at 或 --public")
    at = datetime.strptime(args.at, "%Y-%m-%d %H:%M") if args.at else None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        context = await browser.new_context(storage_state=args.account, user_agent=USER_AGENT, viewport={"width": 1500, "height": 1000})
        studio = Studio(await context.new_page(), Path(args.shots))
        try:
            await studio.open_videos()
            if args.command == "list":
                for row in await studio.rows():
                    print(f"{row['vis']:<12} | {row['date']:<30} | {row['title']}")
            else:
                tags = [t.strip() for t in args.tags.split(",") if t.strip()]
                await studio.finish(args.title, at, tags, args.playlist, args.kids, args.rehearse)
        finally:
            await context.storage_state(path=args.account)
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
