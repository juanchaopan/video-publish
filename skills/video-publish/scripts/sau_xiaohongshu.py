"""小红书视频发布，基于 social-auto-upload 的上传器，按小红书创作平台现在的页面改了几步：

- 正文：整段作为一次粘贴送进编辑器。逐字敲键盘时，正文里的 @ 会弹出"提及用户"的候选框，吞掉后面的回车，
  还会挡住之后的话题候选；粘贴不会触发这些弹窗。
- 话题：输入 #话题 后从弹出的候选里选名字完全一致的那一项，没有就选第一项。
- 封面：先关掉"PK 封面"的引导浮层，悬停封面露出"编辑封面"，在封面编辑器里用"上传"换成指定图片，点"完成"。
- 声明：打开"原创声明"（同意《原创声明须知》），内容类型声明选指定的一项（默认"笔记含AI合成内容"），不声明转载。
- 定时：创作平台的定时时间按北京时间填写。传进来的是本机时间，先换算成北京时间再填，填完核对输入框里的值，
  对不上就中止，不会变成立即发布。

由 publish.mjs 调用，在 social-auto-upload 的虚拟环境里运行（PYTHONPATH 指向 social-auto-upload 的目录）：
    python sau_xiaohongshu.py '<JSON 参数>'
参数：account_file、video、image、title、desc、tags、at（"YYYY-MM-DD HH:MM"，本机时间；空字符串表示立即发布）、
original（是否打开原创声明）、declaration（内容类型声明，空字符串表示不声明）、headless、
shots_dir（截图目录：某一步失败时把当时的页面截下来）、rehearse（true 时只走到点"发布"之前，截图后退出，不发布）。
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from uploader.xiaohongshu_uploader.main import (
    XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE,
    XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED,
    XiaoHongShuVideo,
    xiaohongshu_logger,
    xiaohongshu_setup,
)

BEIJING = timezone(timedelta(hours=8))
EARLIEST_SCHEDULE = timedelta(hours=1)
PASTE_INTO_EDITOR = """(text) => {
  const editor = document.querySelector('[contenteditable="true"]');
  editor.focus();
  const data = new DataTransfer();
  data.setData('text/plain', text);
  editor.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }));
}"""


class Rehearsed(Exception):
    """排练模式走到了点"发布"之前。"""


class XiaohongshuVideoPost(XiaoHongShuVideo):
    def __init__(self, shots_dir: str, rehearse: bool, original: bool, declaration: str, **kwargs):
        super().__init__(**kwargs)
        self.shots_dir = Path(shots_dir)
        self.rehearse = rehearse
        self.original = original
        self.declaration = declaration

    async def shot(self, page, name: str) -> Path:
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        path = self.shots_dir / f"xiaohongshu-{name}.png"
        await page.screenshot(path=str(path), full_page=True)
        return path

    async def step(self, page, name: str, action):
        """执行一步；失败时截图并说明是哪一步，然后中止整个发布。"""
        try:
            await action()
        except Exception as exc:
            path = await self.shot(page, f"failed-{name}")
            raise RuntimeError(f"小红书发布在「{name}」这一步失败，截图：{path}") from exc

    async def stop_if_rehearsing(self, page):
        if self.rehearse:
            await page.wait_for_timeout(2000)
            path = await self.shot(page, "rehearsal")
            print(f"排练完成，没有发布。截图：{path}")
            raise Rehearsed()

    async def fill_desc(self, page):
        if not self.desc:
            return

        async def paste():
            await page.locator('p[data-placeholder*="输入正文描述"]').click()
            await page.evaluate(PASTE_INTO_EDITOR, self.desc)
            await page.wait_for_timeout(1000)
            last_line = self.desc.strip().splitlines()[-1].strip()
            if last_line not in await page.locator('[contenteditable="true"]').first.inner_text():
                raise RuntimeError("正文没有粘贴进编辑器")

        await self.step(page, "填写正文", paste)

    async def fill_tags(self, page):
        tags = list(getattr(self, "tags", None) or [])[:10]
        editor = page.locator('[contenteditable="true"]').first
        missed = []
        for tag in tags:
            await editor.click()
            await page.keyboard.press("Control+End")
            await page.keyboard.type(" #" + tag, delay=40)
            items = page.locator('[id^="tippy-"] .items .item')
            try:
                await items.first.wait_for(state="visible", timeout=8000)
                exact = items.filter(has=page.locator("span.name", has_text=f"#{tag}")).first
                choice = exact if await exact.count() else items.first
                await choice.click()
                await page.wait_for_timeout(500)
            except Exception:
                missed.append(tag)
                await page.keyboard.press("Escape")
        if missed:
            xiaohongshu_logger.warning(f"这些话题没有出现候选，保留为普通文字：{'、'.join(missed)}")
        elif tags:
            xiaohongshu_logger.success(f"话题都已选中：{'、'.join(tags)}")

    async def set_thumbnail(self, page, thumbnail_path):
        if not thumbnail_path:
            return

        async def open_editor():
            guide = page.locator("button.pk-cover-guide-confirm")
            if await guide.count():
                await guide.first.click()
                await page.wait_for_timeout(800)
            await page.keyboard.press("Escape")
            cover = page.locator("div.cover-plugin-preview div.default.column").first
            await cover.scroll_into_view_if_needed()
            await cover.hover()
            await page.wait_for_timeout(800)
            await page.locator("div.cover-edit-entry").first.click(force=True)
            await page.get_by_text("上传", exact=True).first.wait_for(state="visible", timeout=40000)

        async def replace_image():
            async with page.expect_file_chooser(timeout=15000) as chooser:
                await page.get_by_text("上传", exact=True).first.click()
            await (await chooser.value).set_files(thumbnail_path)
            await page.wait_for_timeout(6000)

        async def confirm():
            await page.locator("button.mojito-button", has_text="完成").first.click()
            await page.locator("button.mojito-button", has_text="完成").first.wait_for(state="hidden", timeout=30000)

        await self.step(page, "打开封面编辑器", open_editor)
        await self.step(page, "上传封面图片", replace_image)
        await self.step(page, "确认封面", confirm)
        xiaohongshu_logger.success("封面已换成指定图片")

    async def check_original_declaration(self, page):
        async def declare_original():
            row = page.locator("div", has=page.get_by_text("原创声明", exact=True)).filter(has=page.locator("div.d-switch")).last
            toggle = row.locator("div.d-switch").first
            await toggle.scroll_into_view_if_needed()
            await toggle.click()
            await page.wait_for_timeout(1500)
            agree = page.locator("div.d-modal .d-checkbox, div.d-modal input[type=checkbox]").first
            if await agree.count() and await agree.is_visible():
                await agree.click()
            for label in ("声明原创", "确认", "确定", "同意"):
                button = page.locator("div.d-modal button", has_text=label).first
                if await button.count() and await button.is_visible():
                    await button.click()
                    await page.wait_for_timeout(1000)
                    break

        async def declare_content_type():
            select = page.locator("div.d-select", has=page.locator(".d-select-placeholder", has_text="添加内容类型声明")).first
            await select.scroll_into_view_if_needed()
            await select.click()
            option = page.locator(".declaration-drop-down .d-option-name", has_text=self.declaration).first
            await option.wait_for(state="visible", timeout=8000)
            await option.click()
            await page.wait_for_timeout(1000)

        if self.original:
            await self.step(page, "原创声明", declare_original)
            xiaohongshu_logger.success("已声明原创")
        if self.declaration:
            await self.step(page, "内容类型声明", declare_content_type)
            xiaohongshu_logger.success(f"已声明「{self.declaration}」")
        if self.publish_strategy != XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED:
            await self.stop_if_rehearsing(page)

    async def set_schedule_time_xiaohongshu(self, page, publish_date: datetime):
        wanted = publish_date.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")

        async def schedule():
            card = page.locator(".custom-switch-card").filter(has_text="定时发布")
            await card.scroll_into_view_if_needed()
            await card.locator(".d-switch").click()
            time_input = page.locator(".d-datepicker-input-filter input").first
            await time_input.wait_for(state="visible", timeout=8000)
            await time_input.click()
            await time_input.press("Control+A")
            await time_input.type(wanted, delay=30)
            await time_input.press("Enter")
            await page.wait_for_timeout(1000)
            await page.locator("body").click(position={"x": 5, "y": 5})
            await page.wait_for_timeout(1000)
            shown = (await time_input.input_value()).strip()
            if shown != wanted:
                raise RuntimeError(f"定时时间没有填上：输入框里是「{shown}」，想要的是北京时间「{wanted}」")

        await self.step(page, "定时发布", schedule)
        xiaohongshu_logger.success(f"已设置定时发布：北京时间 {wanted}（本机时间 {publish_date:%Y-%m-%d %H:%M}）")
        await self.stop_if_rehearsing(page)


async def main(params: dict) -> None:
    at = params.get("at") or ""
    publish_date = datetime.strptime(at, "%Y-%m-%d %H:%M") if at else 0
    if publish_date and publish_date - datetime.now() < EARLIEST_SCHEDULE:
        sys.exit(f"定时时间 {at} 离现在不到 1 小时（或已经过去），小红书会直接发布。换一个更晚的时间，或者去掉 --at 立即发布。")
    if not await xiaohongshu_setup(params["account_file"], handle=False):
        sys.exit("小红书未登录或登录已过期：先运行 sau xiaohongshu login --account <账号别名>")
    post = XiaohongshuVideoPost(
        shots_dir=params["shots_dir"],
        rehearse=bool(params.get("rehearse")),
        original=bool(params.get("original", True)),
        declaration=params.get("declaration", ""),
        title=params["title"],
        file_path=params["video"],
        desc=params.get("desc") or "",
        tags=params.get("tags") or [],
        publish_date=publish_date,
        account_file=params["account_file"],
        thumbnail_path=params.get("image") or None,
        publish_strategy=XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED if at else XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE,
        debug=False,
        headless=params.get("headless", True),
    )
    try:
        await post.main()
    except Rehearsed:
        return


if __name__ == "__main__":
    asyncio.run(main(json.loads(sys.argv[1])))
