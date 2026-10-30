"""YouTube 视频发布：用 social-auto-upload 的 YouTube 上传器，跳过它自带的登录检查。

自带的检查用无头浏览器打开 YouTube Studio，Studio 对无头浏览器显示"浏览器不受支持"的提示页，不会跳到频道页，
于是把有效的登录误判为失效。这里直接在可见的 Chrome 窗口里上传；登录真的失效时，上传器打开上传页会被转到
Google 登录页并报错。这个上传器不支持定时，只能立即发布（public、unlisted 或 private）；按天发布用 queue.mjs。

由 publish.mjs 调用，在 social-auto-upload 的虚拟环境里运行（PYTHONPATH 指向 social-auto-upload 的目录）：
    python sau_youtube.py '<JSON 参数>'
参数：account_file、video、image、title、desc、tags、playlist、visibility（public / unlisted / private）。
"""
import asyncio
import json
import sys
from pathlib import Path

from uploader.youtube_uploader.main import YouTubeVideo


def main(params: dict) -> None:
    if not Path(params["account_file"]).exists():
        sys.exit("YouTube 未登录：先运行 sau youtube login --account <账号别名> --headed")
    video = YouTubeVideo(
        params["title"],
        params["video"],
        params.get("tags") or [],
        params["account_file"],
        description=params.get("desc") or "",
        thumbnail_path=params.get("image") or None,
        playlist=params.get("playlist") or None,
        visibility=params.get("visibility") or "public",
        debug=False,
        headless=False,
    )
    asyncio.run(video.main())


if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
