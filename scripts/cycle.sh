#!/usr/bin/env bash
# 每小时采集一次；北京时间 12:00 生成午间版，19:00 生成晚间版。
set -u
export TZ=Asia/Shanghai
cd "$(dirname "$0")/.."

git pull --rebase --quiet || exit 1

COLLECT_STATUS=0
python3 scripts/collect.py || COLLECT_STATUS=$?

H=$(date +%H)
BUILD_STATUS=0
if [ "$H" = "12" ]; then
  python3 scripts/build.py --edition "午间" || BUILD_STATUS=$?
elif [ "$H" = "19" ]; then
  python3 scripts/build.py --edition "晚间" || BUILD_STATUS=$?
fi

rm -rf scripts/__pycache__
git config user.name "hotboard-bot"
git config user.email "hotboard-bot@users.noreply.github.com"
git add data reports

if git diff --cached --quiet; then
  echo "没有新数据或报告"
  [ "$COLLECT_STATUS" -eq 0 ] && [ "$BUILD_STATUS" -eq 0 ]
  exit $?
fi

git commit -q -m "热榜采集与报告 $(date '+%Y-%m-%d %H:%M')（北京时间）"
for i in 1 2 3; do
  if git pull --rebase --quiet && git push --quiet; then
    [ "$COLLECT_STATUS" -eq 0 ] && [ "$BUILD_STATUS" -eq 0 ]
    exit $?
  fi
  sleep 5
done
echo "推送失败"
exit 1
