---
name: video-publish
description: 把做好的视频发到小红书（RedNote）、B 站、YouTube、TikTok：从发布文案读标题、正文、标签，上传视频和自定义封面，打原创和 AI 生成内容声明，由平台定时发布（一天一集也行），并能列出、删除小红书笔记，查看 B 站稿件和 YouTube 视频。用户说"发到小红书/B 站/YouTube/TikTok""定时发布""上传视频""排期""一天发一集""删掉那条笔记"时使用。基于开源的 social-auto-upload，四个平台的上传流程都按平台当前的页面做过。
---

# 视频发布

用 [social-auto-upload](https://github.com/dreammis/social-auto-upload)（MIT）的登录和部分上传器。它自带的流程大多跟不上平台当前的页面，本技能的脚本把每个平台都做对了，四个平台都能上传封面、设定时，由平台到点自己发布，电脑不用开着：

| 平台 | 本技能的做法 | 解决的问题 |
|---|---|---|
| 小红书 | `scripts/sau_xiaohongshu.py` 继承它的上传器 | 自带流程把笔记声明成"转载"、封面点不开、正文里的 @ 弹出提及框吞掉换行并挡住话题、定时按本机时间填（平台按北京时间算，于是直接发布）。不要直接用 `sau xiaohongshu upload-video` 或仓库自带的 xiaohongshu-upload 技能 |
| B 站 | 直接用 `sau bilibili upload-video`（biliup 走接口） | 本来就可靠；默认按"自制"投稿；没有 AI 声明选项 |
| YouTube | `scripts/sau_youtube.py` 传成草稿，`scripts/yt_studio.py` 补全并定时 | 自带上传器停在必填的"是否为儿童内容"上，找不到发布按钮却报成功；标签藏在"展开"里没填；不支持定时；登录检查用无头浏览器被"浏览器不受支持"页拦住 |
| TikTok | `scripts/sau_tiktok.py` 直接操作 TikTok Studio | 自带上传器找的外层容器在页面上已经不存在；封面、定时、AI 标记都由本脚本完成 |

## 文件

| 文件 | 作用 |
|---|---|
| `scripts/publish.mjs` | 入口：读发布文案，调用对应平台的上传脚本，记发布记录防止重复 |
| `scripts/sau_xiaohongshu.py` | 小红书：粘贴正文、选话题、换封面、原创和内容类型声明、按北京时间定时、排练模式 |
| `scripts/sau_youtube.py` | YouTube：在可见窗口里把视频传成私享草稿（标题、简介、缩略图） |
| `scripts/yt_studio.py` | YouTube Studio：列出视频；把草稿补全（儿童内容、标签、播放列表，没有就新建）并定时或公开；排练模式 |
| `scripts/sau_tiktok.py` | TikTok：上传、粘贴说明文字、换封面、AI-generated content 标记、定时、排练模式 |
| `scripts/xhs_notes.py` | 小红书笔记列表（含"定时发布"状态）；按完整标题删除一篇笔记 |
| `scripts/queue.mjs` | 发布队列：平台不能定时时，配合系统定时任务按天立即发布（四个平台都能定时，一般用不到） |

## 一次性准备

1. 安装 social-auto-upload（默认位置 `~/tools/social-auto-upload`，别的位置用环境变量 `SAU_DIR` 指定）：
   ```
   git clone --depth 1 https://github.com/dreammis/social-auto-upload.git ~/tools/social-auto-upload
   cd ~/tools/social-auto-upload
   uv venv --python 3.12 && uv pip install -e . && uv pip install playwright
   .venv/Scripts/patchright install chromium
   .venv/Scripts/python -m playwright install chromium
   ```
   复制 `conf.example.py` 为 `conf.py`，设 `LOCAL_CHROME_HEADLESS = False`（TikTok 登录要看得见窗口），`LOCAL_CHROME_PATH` 指向本机的 Chrome。
2. 登录（账号别名默认 `main`）。都需要账号主人在电脑前操作，先确认用户在电脑前再开窗口：
   - 小红书：`sau xiaohongshu login --account main --headed`，用手机 App 扫码。
   - B 站：`sau bilibili login --account main`，**必须在用户自己的终端里运行**（它要求交互式终端），扫码；二维码显示不全就打开 SAU_DIR 下的 `qrcode.png`。Windows 上让用户打开 PowerShell 运行 `cd <SAU_DIR>; .venv\Scripts\sau.exe bilibili login --account main`；在 Claude Code 里用 `!` 前缀时走的是 Git Bash，路径要写成 `/c/Users/...` 的正斜杠形式。登录后用 `sau bilibili check --account main` 确认，输出 `valid`。
   - YouTube：`sau youtube login --account main --headed`，在弹出的浏览器里登录 Google，10 分钟内没登录会超时。`sau youtube check` 会误报 `invalid`，用 `yt_studio.py <cookie> list` 能列出视频就说明登录有效。Google 会轮换会话 cookie，`yt_studio.py` 每次运行后把新的登录状态写回；隔久了上传报"登录态失效"就重新登录。Studio 界面需要是英文。
   - TikTok：`python examples/get_tk_cookie.py`（在 SAU_DIR 里用虚拟环境的 python），在窗口里登录后，点 Playwright Inspector 里的继续（▶）保存，生成 `cookies/tk_uploader/account.json`。

## 发布文案的格式

一个 Markdown 文件，每个平台一节，字段用加粗标签开头，内容写在下面几行（或同一行冒号后）：

```
## 小红书 ……
**标题**（20 字以内）
……
**正文**
……
**话题**
#话题一 #话题二

## B 站 ……
**标题** / **简介** / **标签**（逗号分隔）

## YouTube ……
**Title** / **Description** / **Tags**（逗号分隔） / **Playlist**: 名称

## TikTok ……
**Caption**
整段说明文字，话题直接写在里面：#tag1 #tag2
```

## 发一条

1. **先看文件**：视频、封面、文案都在；小红书用竖屏视频和 3:4 封面，B 站和 YouTube 用横屏视频和 16:9 封面，TikTok 用竖屏视频和 3:4 封面。
2. **dry-run**：`node scripts/publish.mjs <平台> --post <文案> --video <视频> --cover <封面> --dry-run`，检查标题、正文、标签解析得对。
3. **第一次或页面改版后先排练**：小红书、TikTok 加 `--rehearse`，在真实页面走完所有步骤，停在提交之前截图（`publish-shots/<平台>-rehearsal.png`），看一眼再正式发。YouTube 的补全步骤用 `yt_studio.py ... finish ... --rehearse`。
4. **正式发布**：去掉 `--dry-run`/`--rehearse`，按需要加 `--at "YYYY-MM-DD HH:MM"`（本机时间）。
   - 用户用 AI 配音或 AI 生成画面时：小红书加 `--declaration "笔记含AI合成内容"`，TikTok 加 `--ai-generated`。B 站没有这个选项，需要时请用户在稿件管理里补。
   - 小红书原创声明默认打开（会代用户同意《原创声明须知》）；不是用户自己的原创内容时加 `--no-original`。
   - YouTube 会先传草稿（一集约半小时，等满上传器的超时），再补全并定时；播放列表不存在会新建为公开列表。
5. **核对**：
   - 小红书：在 SAU_DIR 里运行 `.venv/Scripts/python <技能目录>/scripts/xhs_notes.py cookies/xiaohongshu_main.json list`，定时的笔记显示"定时发布"，刚提交的先显示"审核中"。
   - B 站：`<biliup> -u <SAU_DIR>/cookies/bilibili_main.json list`，`<biliup>` 在 `~/.social-auto-upload/tools/biliup/<平台>/biliup(.exe)`；定时稿件显示"审核中"。
   - YouTube：`yt_studio.py <SAU_DIR>/cookies/youtube_main.json list`，定时的显示 Scheduled 和日期。
   - TikTok：请用户在 TikTok Studio 的 Posts 里看一眼。

## 一天发一集

每集一条 `publish.mjs` 命令，各自带 `--at`，平台到点自己发。时间限制：小红书至少比现在晚 1 小时、最多 14 天；B 站至少晚 4 小时、最多 15 天；TikTok 至少晚 20 分钟、最多 10 天，分钟取 5 的倍数。面向中国大陆观众时，晚上 8 点（北京时间）是常用时段；本机在北美东部时，夏令时对应早上 8 点、冬令时对应早上 7 点。

## 规则

- 发布、删除都会公开影响用户的账号：发之前把平台、标题、时间告诉用户；删除前必须得到用户明确同意（`xhs_notes.py delete` 先不加 `--confirm` 核对确认框）。
- 上传失败或结果不明时，先用上面的核对办法确认有没有发出去，再重试。上传器报成功也不等于发出去了，每个平台第一次都要核对。
- `published.json` 里已有的记录会拦住重复发布。同一个记录文件不要让两批发布同时写（各自读取后写回，会互相覆盖记录）；多个平台同时发时，给每个平台用不同的 `--log`，或者一批发完再发下一批。
- 长时间的批量上传可能被 Claude Code 在内存紧张时停掉；这种情况下让用户在自己的 PowerShell 里运行同样的命令。
- 某一步失败会中止并截图（`publish-shots/<平台>-failed-<步骤>.png`）；页面又改版时，看截图，改对应脚本里的那一步，用排练模式验证。
- 不要读取、复制或提交 cookies 目录里的登录文件；发布记录和截图里可能有账号名，也不要提交到公开仓库。
