#!/usr/bin/env node
// 发布队列：给不支持定时（YouTube）或定时不可靠（TikTok）的平台按天发布。
// 队列文件列出每一条要发的内容和时间；每次运行，把"时间已到、还没发过"的条目逐条立即发布。
// 配合系统的定时任务每天运行一次（错过了就在开机后补跑），就能一天发一集。
//
// 用法：node queue.mjs <队列.json> [--dry-run]
//   --dry-run  只列出现在该发的条目，不发布
// 队列格式（路径相对队列文件所在目录）：
//   [{ "platform": "youtube", "post": "content/ep1-en-post.md", "video": "out/ep1-en-horizontal.mp4",
//      "cover": "out/ep1-en-thumb.png", "key": "ep1-en", "at": "2026-10-29 18:00",
//      "log": "out/published.json", "args": ["--declaration", "..."] }]
// 某条发布失败就记下来，跳过它继续下一条；下次运行会再试（发布记录里没有它）。
// 每次运行的输出追加到队列文件旁边的 queue-run.log。
import { appendFileSync, existsSync, readFileSync } from 'node:fs';
import { dirname, extname, basename, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const queueFile = process.argv[2] && resolve(process.argv[2]);
if (!queueFile || !existsSync(queueFile)) {
  console.error('用法：node queue.mjs <队列.json> [--dry-run]');
  process.exit(1);
}
const dryRun = process.argv.includes('--dry-run');
const base = dirname(queueFile);
const runLog = join(base, 'queue-run.log');
const write = (text) => {
  process.stdout.write(text);
  appendFileSync(runLog, text);
};

const pad = (n) => String(n).padStart(2, '0');
const now = new Date();
const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;

/** 发布记录里有没有这一条（平台 + 名字）。 */
function published(item) {
  const video = resolve(base, item.video);
  const logFile = resolve(base, item.log ?? join(dirname(video), 'published.json'));
  if (!existsSync(logFile)) return false;
  const key = item.key ?? basename(video, extname(video));
  return JSON.parse(readFileSync(logFile, 'utf8')).some((entry) => entry.platform === item.platform && entry.id === key);
}

const queue = JSON.parse(readFileSync(queueFile, 'utf8'));
const due = queue.filter((item) => item.at <= stamp && !published(item));
const waiting = queue.filter((item) => item.at > stamp && !published(item));
write(`\n===== ${stamp} 发布队列 ${queueFile}\n现在该发 ${due.length} 条，之后还有 ${waiting.length} 条\n`);
if (dryRun) {
  for (const item of due) write(`  · ${item.platform} ${item.key ?? item.video}（计划 ${item.at}）\n`);
  process.exit(0);
}

let failed = 0;
for (const item of due) {
  const args = [
    join(import.meta.dirname, 'publish.mjs'),
    item.platform,
    '--post', resolve(base, item.post),
    '--video', resolve(base, item.video),
    '--cover', resolve(base, item.cover),
    ...(item.key ? ['--key', item.key] : []),
    ...(item.log ? ['--log', resolve(base, item.log)] : []),
    ...(item.args ?? []),
  ];
  write(`\n--- ${item.platform} ${item.key ?? item.video}（计划 ${item.at}）\n`);
  const result = spawnSync(process.execPath, args, { cwd: base, encoding: 'utf8' });
  write((result.stdout ?? '') + (result.stderr ?? ''));
  if (result.status !== 0) {
    failed += 1;
    write(`!!! 失败（退出码 ${result.status}），下次运行再试\n`);
  }
}
write(`===== 结束：成功 ${due.length - failed} 条，失败 ${failed} 条\n`);
process.exit(failed ? 1 : 0);
