#!/usr/bin/env python3
"""把某一天的全部快照合并成一份汇总，便于每天采集时一次读完。

输出 data/YYYY-MM-DD/summary.json 和 summary.md：
每个标题记录 首次出现、最后出现、出现次数、最高排名、出现在哪些榜。
同时删除 KEEP_DAYS 天以前的数据，控制仓库大小。
用法：python scripts/rollup.py [YYYY-MM-DD ...]   （默认今天和昨天，北京时间）
"""
import glob
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP_DAYS = 30


def key(title):
    return re.sub(r"[\s#，。、！？：；“”‘’（）()【】\[\]《》,.!?:;\"'·…—-]", "", title).lower()


def rollup(day):
    d = os.path.join(ROOT, "data", day)
    snaps = sorted(p for p in glob.glob(os.path.join(d, "[0-9][0-9][0-9][0-9].json")))
    if not snaps:
        return None
    topics, health = {}, {}
    for p in snaps:
        hhmm = os.path.basename(p)[:4]
        stamp = f"{hhmm[:2]}:{hhmm[2:]}"
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
        for sid, src in s["sources"].items():
            h = health.setdefault(sid, {"name": src["name"], "ok": 0, "fail": 0, "last_error": ""})
            if src["ok"]:
                h["ok"] += 1
            else:
                h["fail"] += 1
                h["last_error"] = src.get("error", "")
            for it in src["items"]:
                k = key(it["title"])
                if not k:
                    continue
                t = topics.setdefault(k, {"title": it["title"], "url": it["url"], "first_seen": stamp,
                                          "last_seen": stamp, "snapshots": set(), "boards": {}})
                t["last_seen"] = stamp
                t["snapshots"].add(stamp)
                b = t["boards"].setdefault(src["name"], {"best_rank": it["rank"], "hot": it.get("hot", "")})
                if it["rank"] < b["best_rank"]:
                    b["best_rank"], b["hot"] = it["rank"], it.get("hot", "")
    rows = []
    for t in topics.values():
        best = min(b["best_rank"] for b in t["boards"].values())
        rows.append({"title": t["title"], "url": t["url"], "first_seen": t["first_seen"],
                     "last_seen": t["last_seen"], "hours_on_board": len(t["snapshots"]),
                     "board_count": len(t["boards"]), "best_rank": best, "boards": t["boards"]})
    # 排序：上榜平台越多、在榜越久、排名越高越靠前
    rows.sort(key=lambda r: (-r["board_count"], -r["hours_on_board"], r["best_rank"]))
    out = {"date": day, "snapshots": len(snaps),
           "snapshot_times": [os.path.basename(p)[:4] for p in snaps],
           "source_health": health, "topic_count": len(rows), "topics": rows}
    with open(os.path.join(d, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)

    lines = [f"# {day} 热榜汇总", "",
             f"快照 {len(snaps)} 次；去重后 {len(rows)} 个标题。", "", "## 来源健康", "",
             "| 来源 | 成功 | 失败 | 最近错误 |", "|---|---|---|---|"]
    for h in health.values():
        lines.append(f"| {h['name']} | {h['ok']} | {h['fail']} | {h['last_error'][:60]} |")
    lines += ["", "## 全部标题（按上榜平台数、在榜小时数、最高排名排序）", "",
              "| # | 标题 | 平台数 | 在榜次数 | 最高排名 | 首次—最后 | 平台 |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        boards = "、".join(f"{n}{b['best_rank']}" for n, b in r["boards"].items())
        title = r["title"].replace("|", "｜")
        lines.append(f"| {i} | [{title}]({r['url']}) | {r['board_count']} | {r['hours_on_board']} | "
                     f"{r['best_rank']} | {r['first_seen']}—{r['last_seen']} | {boards} |")
    with open(os.path.join(d, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(snaps), len(rows)


def prune():
    cutoff = (datetime.now(BJ) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    for d in glob.glob(os.path.join(ROOT, "data", "????-??-??")):
        if os.path.basename(d) < cutoff:
            shutil.rmtree(d)


def main():
    days = sys.argv[1:]
    if not days:
        now = datetime.now(BJ)
        days = [now.strftime("%Y-%m-%d"), (now - timedelta(days=1)).strftime("%Y-%m-%d")]
    for day in days:
        r = rollup(day)
        if r:
            print(f"{day}: {r[0]} 次快照，{r[1]} 个标题")
    prune()


if __name__ == "__main__":
    main()
