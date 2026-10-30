"""TikTok 视频发布：直接操作 TikTok Studio 的上传页（social-auto-upload 的 TikTok 上传器找的外层容器已经不存在）。

步骤：选视频文件 → 等上传完（"Post"按钮可用）→ 关掉各种提示（"开启自动检查"点开启，"在手机上预览"点知道了）→
粘贴说明文字（含话题）→ "Edit cover"里点"Upload cover"换成封面图，点"Save" → 需要时在"Show more"里打开
"AI-generated content"标记 → 定时（先同意"保存视频以便定时"，再在日历和时间选择器里选好，核对输入框的值）→
点页面最下方的提交按钮（立即发布时叫"Post"，定时时叫"Schedule"），等页面跳到作品列表。

用无头浏览器加普通 Chrome 的 User-Agent；结束时把更新后的登录状态写回 cookie 文件。定时的时间按浏览器所在时区
（本机时区）理解，分钟只能是 5 的倍数。

由 publish.mjs 调用，在 social-auto-upload 的虚拟环境里运行（PYTHONPATH 指向 social-auto-upload 的目录）：
    python sau_tiktok.py '<JSON 参数>'
参数：account_file、video、image、caption、at（"YYYY-MM-DD HH:MM"，本机时间；空字符串表示立即发布）、ai_generated、
shots_dir、rehearse（true 时走完所有步骤、截图，不点提交；某一步失败也继续往下走，方便一次看清所有步骤）。
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from patchright.async_api import async_playwright

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
EARLIEST_SCHEDULE = timedelta(minutes=20)
POPUP_BUTTONS = ("Got it", "Turn on")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
PASTE = """(text) => {
  const editor = document.querySelector('.public-DraftEditor-content');
  editor.focus();
  const data = new DataTransfer();
  data.setData('text/plain', text);
  editor.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }));
}"""
# 最后一个可见、文字正好等于指定内容的元素：先滚到屏幕中间，再返回它的中心点（弹窗总是加在页面最后，所以取最后一个）。
VISIBLE_TEXT = """(text) => {
  const hits = [...document.querySelectorAll('*')].filter(e =>
    !e.children.length && e.innerText && e.innerText.trim() === text && e.getBoundingClientRect().height > 0);
  if (!hits.length) return null;
  const target = hits[hits.length - 1];
  target.scrollIntoView({ block: 'center' });
  const r = target.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}"""
# 页面上位置最靠下、可见、文字正好等于指定内容的按钮：先滚到屏幕中间，再返回中心点和它是否可用。
SUBMIT_BUTTON = """(label) => {
  const buttons = [...document.querySelectorAll('button')].filter(b =>
    b.innerText && b.innerText.trim() === label && b.getBoundingClientRect().height > 0);
  if (!buttons.length) return null;
  buttons.sort((a, b) => (a.getBoundingClientRect().top + scrollY) - (b.getBoundingClientRect().top + scrollY));
  const button = buttons[buttons.length - 1];
  button.scrollIntoView({ block: 'center' });
  const r = button.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, enabled: !button.disabled && button.getAttribute('aria-disabled') !== 'true' };
}"""
CONTROLS = """() => [...document.querySelectorAll('button, input, span, li, [role=radio], [role=switch], [role=tab], [role=option], [role=gridcell], label')]
  .filter(e => { const r = e.getBoundingClientRect(); return r.height > 0 && r.top >= 0 && r.top < innerHeight; })
  .map(e => e.tagName + (e.type ? '[' + e.type + ']' : '') + (e.getAttribute('role') ? '{' + e.getAttribute('role') + '}' : '') + '.' + [...e.classList].slice(0, 3).join('.') + ' :: ' + (e.children.length ? '' : (e.innerText || e.value || '').trim().slice(0, 30)))
  .filter(s => !s.endsWith(':: '))"""


class Rehearsed(Exception):
    pass


class TikTokPost:
    def __init__(self, page, params: dict):
        self.page = page
        self.p = params
        self.shots = Path(params["shots_dir"])
        self.rehearse = bool(params.get("rehearse"))

    async def shot(self, name: str) -> Path:
        self.shots.mkdir(parents=True, exist_ok=True)
        path = self.shots / f"tiktok-{name}.png"
        await self.page.screenshot(path=str(path))
        if self.rehearse:
            (self.shots / f"tiktok-{name}.txt").write_text("\n".join(await self.page.evaluate(CONTROLS)), encoding="utf-8")
        return path

    async def step(self, name: str, action):
        try:
            await self.dismiss_popups()
            await action()
            if self.rehearse:
                await self.shot(name)
        except Exception as exc:
            path = await self.shot(f"failed-{name}")
            if self.rehearse:
                print(f"排练：「{name}」失败（{str(exc).splitlines()[0]}），截图：{path}")
                return
            raise RuntimeError(f"TikTok 发布在「{name}」这一步失败，截图：{path}") from exc

    async def click_text(self, text: str):
        point = await self.page.evaluate(VISIBLE_TEXT, text)
        if point is None:
            raise RuntimeError(f"页面上没有可见的「{text}」")
        await self.page.wait_for_timeout(500)
        point = await self.page.evaluate(VISIBLE_TEXT, text)
        await self.page.mouse.click(point["x"], point["y"])

    async def dismiss_popups(self):
        for label in POPUP_BUTTONS:
            button = self.page.get_by_role("button", name=label, exact=True)
            if await button.count() and await button.first.is_visible():
                await button.first.click()
                await self.page.wait_for_timeout(800)

    async def choose_date(self, date_input, at: datetime):
        page = self.page
        await date_input.click()
        await page.locator("span.month-title").first.wait_for(timeout=8000)
        for _ in range(24):
            month = (await page.locator("span.month-title").first.inner_text()).strip()
            year = int((await page.locator("span.year-title").first.inner_text()).strip())
            shown = year * 12 + MONTHS.index(month)
            wanted = at.year * 12 + at.month - 1
            if shown == wanted:
                break
            arrows = page.locator("span.arrow")
            await (arrows.last if shown < wanted else arrows.first).click()
            await page.wait_for_timeout(600)
        days = page.locator("span.day.valid").filter(has_text=str(at.day))
        for i in range(await days.count()):
            if (await days.nth(i).inner_text()).strip() == str(at.day):
                await days.nth(i).click()
                await page.wait_for_timeout(800)
                return
        raise RuntimeError(f"日历里 {at:%Y-%m} 没有可选的 {at.day} 日")

    async def choose_time(self, time_input, at: datetime):
        page = self.page
        await time_input.click()
        await page.wait_for_timeout(1200)
        minute = f"{at.minute - at.minute % 5:02d}"
        for column, value in (("left", f"{at:%H}"), ("right", minute)):
            options = page.locator(f"span.tiktok-timepicker-{column}")
            for i in range(await options.count()):
                if (await options.nth(i).inner_text()).strip() == value:
                    await options.nth(i).scroll_into_view_if_needed()
                    await options.nth(i).click()
                    await page.wait_for_timeout(800)
                    break
            else:
                await self.shot("time-picker")
                raise RuntimeError(f"时间选择器里没有 {value}")
        if await page.locator("span.tiktok-timepicker-left").first.is_visible():
            await time_input.click()
            await page.wait_for_timeout(600)

    async def run(self):
        page = self.page
        at = datetime.strptime(self.p["at"], "%Y-%m-%d %H:%M") if self.p.get("at") else None

        async def open_upload():
            await page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            file_input = page.locator("input[type=file][accept*=video]").first
            await file_input.wait_for(state="attached", timeout=30000)
            if "login" in page.url:
                raise RuntimeError("TikTok 登录已失效：重新运行 examples/get_tk_cookie.py")
            await file_input.set_input_files(self.p["video"])

        async def wait_uploaded():
            post = page.locator("button", has_text="Post").last
            for _ in range(240):
                await self.dismiss_popups()
                ready = await post.count() and await post.get_attribute("disabled") is None and await post.get_attribute("aria-disabled") != "true"
                if ready and not await page.get_by_text("Checks can only start after the file is uploaded").count():
                    return
                await page.wait_for_timeout(2500)
            raise RuntimeError("10 分钟内视频没有传完")

        async def caption():
            editor = page.locator(".public-DraftEditor-content").first
            await editor.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Delete")
            await page.evaluate(PASTE, self.p["caption"])
            await page.wait_for_timeout(1500)
            await page.keyboard.press("Escape")
            text = await editor.inner_text()
            last_line = self.p["caption"].strip().splitlines()[-1].strip()[:20]
            if last_line not in text:
                raise RuntimeError("说明文字没有粘贴进去")

        async def cover():
            await self.click_text("Edit cover")
            await page.get_by_text("Upload cover", exact=True).first.wait_for(timeout=20000)
            await page.wait_for_timeout(1500)
            async with page.expect_file_chooser(timeout=15000) as chooser:
                await self.click_text("Upload cover")
            await (await chooser.value).set_files(self.p["image"])
            await page.wait_for_timeout(5000)
            await self.click_text("Save")
            await page.get_by_text("Preview in profile", exact=False).first.wait_for(state="hidden", timeout=30000)
            await page.wait_for_timeout(1500)

        async def ai_label():
            await self.click_text("Show more")
            await page.wait_for_timeout(1500)
            row = page.locator("div", has=page.get_by_text("AI-generated content", exact=True)).filter(has=page.locator("input[type=checkbox]")).last
            switch = row.locator("input[type=checkbox]").first
            await switch.scroll_into_view_if_needed()
            if not await switch.is_checked():
                await switch.click(force=True)
                await page.wait_for_timeout(1500)
                await self.dismiss_popups()
            if not await switch.is_checked():
                raise RuntimeError("AI-generated content 开关没有打开")

        async def schedule():
            await self.click_text("Schedule")
            await page.wait_for_timeout(1500)
            allow = page.get_by_role("button", name="Allow")
            if await allow.count() and await allow.first.is_visible():
                await allow.first.click()
                await page.wait_for_timeout(1500)
            inputs = page.locator("input.TUXTextInputCore-input")
            time_input = date_input = None
            for i in range(await inputs.count()):
                value = await inputs.nth(i).input_value()
                if len(value) == 5 and value[2] == ":":
                    time_input = inputs.nth(i)
                elif len(value) == 10 and value[4] == "-":
                    date_input = inputs.nth(i)
            if time_input is None or date_input is None:
                raise RuntimeError("没有找到定时的时间框和日期框")
            wanted_date = f"{at:%Y-%m-%d}"
            wanted_time = f"{at:%H}:{at.minute - at.minute % 5:02d}"
            if await date_input.input_value() != wanted_date:
                await self.choose_date(date_input, at)
            if await time_input.input_value() != wanted_time:
                await self.choose_time(time_input, at)
            shown = (await date_input.input_value(), await time_input.input_value())
            if shown != (wanted_date, wanted_time):
                raise RuntimeError(f"定时没有填上：显示的是 {shown[0]} {shown[1]}，想要的是 {wanted_date} {wanted_time}")

        await self.step("打开上传页并选视频", open_upload)
        await self.step("等视频传完", wait_uploaded)
        await self.step("说明文字", caption)
        if self.p.get("image"):
            await self.step("封面", cover)
        if self.p.get("ai_generated"):
            await self.step("AI 生成内容标记", ai_label)
        if at:
            await self.step("定时", schedule)
        if self.rehearse:
            path = await self.shot("rehearsal")
            print(f"排练完成，没有发布。截图：{path}")
            raise Rehearsed()

        async def submit():
            label = "Schedule" if at else "Post"
            target = await page.evaluate(SUBMIT_BUTTON, label)
            if target is None:
                raise RuntimeError(f"页面上没有可见的「{label}」按钮")
            if not target["enabled"]:
                raise RuntimeError(f"「{label}」按钮是灰的，还不能提交")
            await page.wait_for_timeout(500)
            target = await page.evaluate(SUBMIT_BUTTON, label)
            await page.mouse.click(target["x"], target["y"])
            await page.wait_for_url("**/tiktokstudio/content**", timeout=120000)

        await self.step("提交", submit)
        print("TikTok 已提交" + (f"，定时 {at:%Y-%m-%d %H:%M}" if at else "，立即发布"))


async def main(params: dict):
    at = params.get("at") or ""
    if at and datetime.strptime(at, "%Y-%m-%d %H:%M") - datetime.now() < EARLIEST_SCHEDULE:
        sys.exit(f"定时时间 {at} 离现在太近（或已经过去），换一个至少 20 分钟以后的时间，或者去掉 --at 立即发布。")
    if not Path(params["account_file"]).exists():
        sys.exit("TikTok 未登录：先运行 examples/get_tk_cookie.py")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        context = await browser.new_context(storage_state=params["account_file"], user_agent=USER_AGENT, viewport={"width": 1400, "height": 1100})
        try:
            await TikTokPost(await context.new_page(), params).run()
        except Rehearsed:
            pass
        finally:
            await context.storage_state(path=params["account_file"])
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main(json.loads(sys.argv[1])))
