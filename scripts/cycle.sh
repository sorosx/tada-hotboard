#!/usr/bin/env bash
# 采集一次快照 → 需要时生成日报 → 提交推送。由两个工作流共用。
set -u
export TZ=Asia/Shanghai
cd "$(dirname "$0")/.."

git pull --rebase --quiet || true
python3 scripts/collect.py || echo "本次采集没有任何来源成功"

H=$(date +%H)
# 每晚 23 点生成当天报告；0 点再补一次前一天的完整版
if [ "$H" = "23" ]; then python3 scripts/build.py --date "$(date +%F)"; fi
if [ "$H" = "00" ]; then python3 scripts/build.py --date "$(date -d yesterday +%F)"; fi
rm -rf scripts/__pycache__

git config user.name "hotboard-bot"
git config user.email "hotboard-bot@users.noreply.github.com"
git add data reports 2>/dev/null || git add data
if git diff --cached --quiet; then
  echo "没有新数据"; exit 0
fi
git commit -q -m "快照 $(date '+%Y-%m-%d %H:%M')（北京时间）"
for i in 1 2 3; do
  git pull --rebase --quiet && git push --quiet && exit 0
  sleep 5
done
echo "推送失败"; exit 1
