#!/usr/bin/env node
// 发布一条视频：从发布文案（Markdown）里读出某个平台的标题、正文和标签，上传视频和封面，立即发布或由平台定时发布。
//
// 用法：node publish.mjs <平台> --post <文案.md> --video <视频> --cover <封面图> [选项]
//   平台：xiaohongshu、bilibili、youtube、tiktok
//   --at "YYYY-MM-DD HH:MM"   定时发布的本机时间；不写就立即发布。四个平台都由平台自己定时（小红书按北京时间排期，
//                             换算在 sau_xiaohongshu.py 里完成）
//   --dry-run                 只打印要发的内容，不打开浏览器
//   --rehearse                小红书、TikTok：在真实页面上走完所有步骤，停在点"发布"之前并截图，不发布
//   --headed                  小红书：显示浏览器窗口（出现人机验证时用）
//   --declaration "<声明>"     小红书的内容类型声明，例如 "笔记含AI合成内容"；不写就不声明
//   --no-original             小红书：不打开原创声明（默认打开）
//   --ai-generated            TikTok：打开"AI-generated content"标记
//   --key <名字>              记录用的名字，默认是视频文件名（不含扩展名）
//   --log <文件>              发布记录，默认是视频所在目录下的 published.json；同一个名字在同一平台发过就拒绝再发
//   --force                   已经发过时仍然再发一次
// 环境变量：SAU_DIR 是 social-auto-upload 的目录，默认 ~/tools/social-auto-upload；SAU_ACCOUNT 是登录时起的账号别名，
//           默认 main；BILIBILI_TID 是 B 站分区号，默认 231（科技 · 计算机技术）。
// 失败时的页面截图放在发布记录旁边的 publish-shots/ 目录。
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, extname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const PLATFORMS = {
  xiaohongshu: { section: '小红书' },
  bilibili: { section: 'B 站' },
  youtube: { section: 'YouTube' },
  tiktok: { section: 'TikTok' },
};
const VALUE_OPTIONS = ['--post', '--video', '--cover', '--at', '--declaration', '--key', '--log'];
const REHEARSABLE = ['xiaohongshu', 'tiktok'];

const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const option = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);
const [platform] = args.filter((arg, i) => !arg.startsWith('--') && !VALUE_OPTIONS.includes(args[i - 1]));
const usage = `用法：node publish.mjs <${Object.keys(PLATFORMS).join('|')}> --post <文案.md> --video <视频> --cover <封面图> [--at "YYYY-MM-DD HH:MM"] [--dry-run] [--rehearse] [--headed] [--declaration "<声明>"] [--no-original] [--ai-generated] [--key <名字>] [--log <文件>] [--force]`;

const config = PLATFORMS[platform];
const postFile = option('--post');
const video = option('--video') && resolve(option('--video'));
const cover = option('--cover') && resolve(option('--cover'));
const at = option('--at');
const rehearse = flag('--rehearse');
if (!config || !postFile || !video || !cover) {
  console.error(usage);
  process.exit(1);
}
if (at && !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(at)) {
  console.error('--at 的格式是 "YYYY-MM-DD HH:MM"');
  process.exit(1);
}
if (rehearse && !REHEARSABLE.includes(platform)) {
  console.error(`--rehearse 只支持 ${REHEARSABLE.join('、')}`);
  process.exit(1);
}

/** 取出 "## <平台>..." 这一节的正文。 */
function sectionOf(markdown, heading) {
  const part = markdown.split(/^## /m).find((p) => p.startsWith(heading));
  if (!part) throw new Error(`发布文案里没有"## ${heading}"这一节`);
  return part;
}

/** 取出 "**<字段>**" 后面的内容：同一行冒号后的文字，或者下面直到下一个加粗字段为止的几行。 */
function fieldOf(section, label) {
  const lines = section.split('\n');
  const start = lines.findIndex((line) => line.startsWith(`**${label}**`));
  if (start < 0) return '';
  const inline = lines[start].slice(`**${label}**`.length).replace(/^[：:]\s*/, '').trim();
  if (inline && !inline.startsWith('（')) return inline;
  const end = lines.findIndex((line, i) => i > start && /^\*\*[^*]+\*\*/.test(line));
  return lines.slice(start + 1, end < 0 ? undefined : end).join('\n').trim();
}

const hashtags = (text) => [...text.matchAll(/#([^\s#]+)/g)].map((m) => m[1]);
const listOf = (text) => text.split(/[,，]\s*/).map((t) => t.trim()).filter(Boolean);

const section = sectionOf(readFileSync(postFile, 'utf8'), config.section);
let post;
if (platform === 'xiaohongshu') {
  post = { title: fieldOf(section, '标题'), desc: fieldOf(section, '正文'), tags: hashtags(fieldOf(section, '话题')) };
} else if (platform === 'bilibili') {
  post = { title: fieldOf(section, '标题'), desc: fieldOf(section, '简介'), tags: listOf(fieldOf(section, '标签')) };
} else if (platform === 'youtube') {
  post = { title: fieldOf(section, 'Title'), desc: fieldOf(section, 'Description'), tags: listOf(fieldOf(section, 'Tags')), playlist: fieldOf(section, 'Playlist') };
} else {
  const caption = fieldOf(section, 'Caption');
  post = { title: caption.split('\n')[0].trim(), desc: caption, tags: hashtags(caption) };
}
if (!post.title) {
  console.error(`发布文案"## ${config.section}"这一节里没有标题`);
  process.exit(1);
}

const key = option('--key') ?? basename(video, extname(video));
const logFile = resolve(option('--log') ?? join(dirname(video), 'published.json'));
const shotsDir = join(dirname(logFile), 'publish-shots');

console.log(`== ${platform} · ${key} · ${at ? `定时 ${at}（本机时间）` : '立即发布'}${rehearse ? ' · 排练，不发布' : ''}`);
console.log(`视频：${video}\n封面：${cover}\n标题：${post.title}\n标签：${post.tags.join(', ')}`);
if (post.playlist) console.log(`播放列表：${post.playlist}`);
console.log(`正文：\n${post.desc || '（标题即正文）'}\n`);

for (const file of [video, cover]) {
  if (!existsSync(file)) {
    console.error(`缺少文件：${file}`);
    process.exit(1);
  }
}
const log = existsSync(logFile) ? JSON.parse(readFileSync(logFile, 'utf8')) : [];
if (!rehearse && log.some((entry) => entry.platform === platform && entry.id === key) && !flag('--force')) {
  console.error(`${key} 已经发过 ${platform}（见 ${logFile}）。确实要再发一次，加 --force。`);
  process.exit(1);
}
if (flag('--dry-run')) process.exit(0);

const sauDir = process.env.SAU_DIR ?? join(homedir(), 'tools', 'social-auto-upload');
if (!existsSync(sauDir)) {
  console.error(`找不到 social-auto-upload：${sauDir}。按技能说明安装，或者用环境变量 SAU_DIR 指定位置。`);
  process.exit(1);
}
const account = process.env.SAU_ACCOUNT ?? 'main';
const windows = process.platform === 'win32';
const bin = (name) => join(sauDir, '.venv', windows ? 'Scripts' : 'bin', windows ? `${name}.exe` : name);
const python = (scriptArgs) =>
  spawnSync(bin('python'), ['-X', 'utf8', ...scriptArgs], { cwd: sauDir, stdio: 'inherit', env: { ...process.env, PYTHONPATH: sauDir } });
const adapter = (name) => join(import.meta.dirname, name);

let result;
if (platform === 'xiaohongshu') {
  const params = {
    ...post,
    video,
    image: cover,
    at: at ?? '',
    account_file: join(sauDir, 'cookies', `xiaohongshu_${account}.json`),
    original: !flag('--no-original'),
    declaration: option('--declaration') ?? '',
    headless: !flag('--headed'),
    shots_dir: shotsDir,
    rehearse,
  };
  result = python([adapter('sau_xiaohongshu.py'), JSON.stringify(params)]);
} else if (platform === 'youtube') {
  // 上传器只能把视频传成草稿（停在必填项上），由 yt_studio.py 打开草稿补全并定时或公开。
  const accountFile = join(sauDir, 'cookies', `youtube_${account}.json`);
  const upload = { ...post, video, image: cover, account_file: accountFile, visibility: 'private' };
  result = python([adapter('sau_youtube.py'), JSON.stringify(upload)]);
  if (result.status === 0) {
    const finish = [adapter('yt_studio.py'), accountFile, 'finish', post.title.slice(0, 60), ...(at ? ['--at', at] : ['--public'])];
    if (post.tags.length) finish.push('--tags', post.tags.join(','));
    if (post.playlist) finish.push('--playlist', post.playlist);
    finish.push('--shots', shotsDir);
    result = python(finish);
  }
} else if (platform === 'tiktok') {
  const params = {
    video,
    image: cover,
    caption: post.desc,
    at: at ?? '',
    ai_generated: flag('--ai-generated'),
    account_file: join(sauDir, 'cookies', 'tk_uploader', 'account.json'),
    shots_dir: shotsDir,
    rehearse,
  };
  result = python([adapter('sau_tiktok.py'), JSON.stringify(params)]);
} else {
  const cli = ['upload-video', '--account', account, '--file', video, '--title', post.title, '--desc', post.desc, '--thumbnail', cover, '--tid', process.env.BILIBILI_TID ?? '231'];
  if (post.tags.length) cli.push('--tags', post.tags.join(','));
  if (at) cli.push('--schedule', at);
  result = spawnSync(bin('sau'), [platform, ...cli], { cwd: sauDir, stdio: 'inherit' });
}

if (result.status !== 0) {
  console.error(`${platform} 上传失败（退出码 ${result.status}）。先到平台的创作者后台确认有没有发出去，再决定要不要重试。`);
  process.exit(result.status ?? 1);
}
if (rehearse) process.exit(0);
log.push({ platform, id: key, at: at ?? null, uploadedAt: new Date().toISOString() });
writeFileSync(logFile, `${JSON.stringify(log, null, 2)}\n`);
console.log(`已记录到 ${logFile}`);
