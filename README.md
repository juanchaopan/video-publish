# video-publish：一个技能发四个平台

一个 Claude Code 插件，把做好的视频发到小红书（RedNote）、B 站、YouTube、TikTok。对 Claude 说"把第 3 集发到小红书，明晚 8 点"，它就从发布文案里读出标题、正文和标签，上传视频和自定义封面，打上原创和 AI 生成内容声明，交给平台定时发布。到点由平台自己发，电脑不用开着。

登录和一部分上传器来自开源的 [social-auto-upload](https://github.com/dreammis/social-auto-upload)（MIT）。它自带的流程大多跟不上平台当前的页面，本插件的脚本把四个平台的上传流程都重新做对了：

| 平台 | 能做什么 |
|---|---|
| 小红书 | 正文、话题、自定义封面、原创声明、内容类型声明（例如"笔记含AI合成内容"）、按北京时间定时；列出和删除笔记 |
| B 站 | 标题、简介、标签、封面、分区、定时（走 biliup 接口） |
| YouTube | 标题、简介、缩略图、标签、"是否为儿童内容"、播放列表（没有就新建）、定时或公开 |
| TikTok | 说明文字和话题、自定义封面、AI-generated content 标记、定时 |

每个平台都有排练模式：在真实页面上走完所有步骤，停在提交之前截图，确认无误再正式发。

## 安装

在 Claude Code 里运行：

```
/plugin marketplace add juanchaopan/video-publish
/plugin install video-publish@video-publish
```

更新时运行 `/plugin marketplace update video-publish`。

也可以把仓库克隆到 `~/.claude/skills/video-publish/`，Claude Code 会把它当作插件自动加载。

装好插件之后，还要在自己的电脑上做一次准备：安装 social-auto-upload，在各平台登录。步骤写在 [`skills/video-publish/SKILL.md`](skills/video-publish/SKILL.md) 的"一次性准备"一节，Claude 第一次使用时会带你走一遍。需要 Node.js、Python 3.12（用 uv 管理）和 Chrome。

## 使用

准备一个发布文案（Markdown），每个平台一节，格式见 SKILL.md 的"发布文案的格式"。然后直接对 Claude 说要发什么、发到哪、什么时间，例如：

- "把 ep3 发到小红书和 B 站，北京时间明晚 8 点"
- "英文版 1 到 6 集每天一集发 TikTok，从明天开始"
- "删掉小红书上标题是 xxx 的那篇笔记"

也可以直接运行入口脚本：

```
node skills/video-publish/scripts/publish.mjs xiaohongshu \
  --post content/ep3-post.md --video out/ep3-vertical.mp4 --cover out/ep3-cover.png \
  --declaration "笔记含AI合成内容" --at "2026-10-31 08:00"
```

发布记录写在 `published.json`，同一个视频在同一平台发过会被拦下，避免重复发布。

## 隐私

- 登录状态（各平台的 cookie）保存在 social-auto-upload 的 `cookies/` 目录里，只在你自己的电脑上，插件不会读取、复制或上传。
- 发布记录和截图写在视频旁边，可能带有账号名，不要提交到公开仓库。
- 插件里没有任何账号信息，账号别名、目录位置、B 站分区都用环境变量配置（见 `publish.mjs` 开头的说明）。

## 风险提示

用脚本自动操作账号，可能不符合部分平台的服务条款，平台也可能因此限制账号。请只用在自己的账号上，发布频率保持正常，自行承担风险。平台页面改版后脚本可能失效；SKILL.md 里写了出错截图的位置和用排练模式修复的办法。

## 许可

MIT。依赖的 social-auto-upload 同样是 MIT 许可，需要单独安装。
