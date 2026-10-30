#!/usr/bin/env python3
"""把一段时间内的热榜快照去重合并，拆成两份报告：

  1. 钱包线索：和普通人钱包有关、且不触红线的标题（给《泰达的账本》选题用）
  2. 新闻汇总：全部去重后的标题，按类别分组（其他用途）

用法：
  python scripts/build.py --date 2026-10-30          # 北京时间整天，写入 reports/
  python scripts/build.py --last 24 --out /some/dir  # 截至现在的过去 24 小时
同时删除 data/ 里 KEEP_DAYS 天以前的快照。

分类是关键词规则，只做粗筛：钱包线索宁多勿漏，最终由人或 Claude 判断和核实。
"""
import argparse
import glob
import gzip
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP_DAYS = 30

# ---------- 关键词规则 ----------
WALLET = [
    # 价格与消费
    "价格", "涨价", "降价", "调价", "物价", "售价", "标价", "原价", "定价", "低价", "高价", "天价", "特价", "比价",
    "克价", "房价", "油价", "电价", "水价", "药价", "菜价", "肉价", "票价", "车价", "金价", "上涨", "下跌", "下调", "上调",
    "便宜", "打折", "折扣", "优惠", "补贴", "消费券", "免费", "收费", "费用", "降费", "涨幅", "降幅",
    "退款", "退费", "退一赔", "赔偿", "赔付", "罚款", "押金", "会员", "扣费", "扣款", "续费", "套路", "维权", "投诉",
    "消协", "召回", "双11", "双十一", "618", "年货", "大促", "预售", "保价", "仅退款", "外卖", "快递", "网购", "带货",
    "汽油", "柴油", "燃气", "天然气", "取暖", "供暖", "话费", "流量", "宽带", "机票", "火车票", "春运", "门票",
    "房租", "租金", "物业", "猪肉", "鸡蛋", "蔬菜", "茅台", "黄金", "金饰", "白银",
    # 收入与就业
    "工资", "薪资", "薪酬", "降薪", "欠薪", "收入", "年终奖", "奖金", "就业", "招聘", "裁员", "失业", "社保", "医保",
    "养老金", "退休", "公积金", "个税", "所得税", "最低工资", "国考", "考公", "考编", "骑手", "网约车",
    "灵活就业", "零工", "工伤", "被AI替代", "AI抢", "AI客服",
    # 房与车
    "房贷", "楼市", "买房", "卖房", "二手房", "新房", "首付", "契税", "现房", "限购", "车贷", "购车", "新能源车",
    "电池", "车险", "保险", "以旧换新",
    # 金融与资产
    "存款", "利率", "利息", "LPR", "贷款", "征信", "信用卡", "花呗", "借呗", "网贷", "理财", "银行",
    "降息", "加息", "汇率", "通胀", "CPI", "PPI", "数字人民币", "诈骗", "骗局", "背债",
    # 政策与生活成本
    "新规", "起施行", "起实施", "新政", "集采", "看病", "挂号", "学费", "育儿", "生育", "托育", "彩礼", "结婚",
    "住院", "体检",
]
# 红线：时政、军事、外交、灾难伤亡等，命中则不进钱包线索（仍保留在新闻汇总里）
POLITICS = [
    "中共", "中央委员会", "全会", "公报", "政治局", "总书记", "主席", "总理", "同志", "简历", "任免", "落马",
    "被查", "双开", "纪委", "巡视", "军", "导弹", "战机", "航母", "演习", "空袭", "开火", "战争", "冲突",
    "外交部", "大使", "台湾", "台海", "两岸", "香港", "新疆", "西藏", "宗教", "民族", "特朗普", "普京",
    "伊朗", "以色列", "乌克兰", "俄罗斯", "朝鲜", "北约", "制裁", "关税战", "国防", "菲律宾", "日本政府",
    "以台", "美军", "领导干部", "党", "政府工作",
]
DISASTER = [
    "死亡", "遇难", "身亡", "伤亡", "坠亡", "地震", "爆炸", "火灾", "事故", "失联", "遇害", "凶手", "命案", "死", "伤", "撞人", "坠", "溺",
]
MINORS = [
    "未成年", "儿童", "学生", "孩子", "女童", "男童", "少女", "少年", "岁女孩", "岁男孩", "小学", "中学", "幼儿园",
]
REDLINE = POLITICS + DISASTER + MINORS
# 文娱体育：只在这些来源出现、且没有钱包关键词的，视为非钱包
FUN = ["姆巴佩", "梅西", "C罗", "球队", "联赛", "西甲", "英超", "意甲", "NBA", "CBA", "比赛", "夺冠", "进球",
       "演唱会", "官宣", "恋情", "离婚", "综艺", "电视剧", "电影", "票房", "主演", "明星", "偶像", "剧", "游戏"]

CATS = [
    ("时政国际", POLITICS),
    ("灾难事故", DISASTER),
    ("财经资产", ["股", "A股", "基金", "银行", "央行", "利率", "汇率", "黄金", "金价", "上市", "财报", "净利润",
                 "营收", "融资", "美联储", "期货", "债", "港股", "美股", "市值"]),
    ("文娱体育", FUN),
    ("科技数码", ["AI", "人工智能", "芯片", "手机", "iPhone", "苹果", "华为", "小米", "大模型", "OpenAI",
                 "机器人", "发布会", "新品", "Pro", "Ultra", "系统", "App", "汽车", "车型", "智驾"]),
    ("民生消费", WALLET),
]


def hits(title, words):
    return [w for w in words if w in title]


def category(title):
    for name, words in CATS:
        if hits(title, words):
            return name
    return "社会其他"


def key(title):
    return re.sub(r"[\s#，。、！？：；“”‘’（）()【】\[\]《》,.!?:;\"'·…—\-|｜]", "", title).lower()


# ---------- 读快照 ----------
def load(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def snapshots(start, end):
    """返回 [start, end) 之间的快照路径（按文件名里的北京时间判断）。"""
    out = []
    for p in glob.glob(os.path.join(ROOT, "data", "????-??-??", "[0-9][0-9][0-9][0-9].json*")):
        day = os.path.basename(os.path.dirname(p))
        hhmm = os.path.basename(p)[:4]
        t = datetime.strptime(day + hhmm, "%Y-%m-%d%H%M").replace(tzinfo=BJ)
        if start <= t < end:
            out.append((t, p))
    return sorted(out)


def merge(snaps):
    topics, health = {}, {}
    for t, p in snaps:
        stamp = t.strftime("%m-%d %H:%M")
        s = load(p)
        for sid, src in s["sources"].items():
            h = health.setdefault(src["name"], {"ok": 0, "fail": 0, "last_error": ""})
            if src["ok"]:
                h["ok"] += 1
            else:
                h["fail"] += 1
                h["last_error"] = src.get("error", "")
            for it in src["items"]:
                k = key(it["title"])
                if len(k) < 4:
                    continue
                x = topics.setdefault(k, {"title": it["title"], "url": it["url"], "first_seen": stamp,
                                          "last_seen": stamp, "seen": set(), "boards": {}})
                x["last_seen"] = stamp
                x["seen"].add(stamp)
                b = x["boards"].setdefault(src["name"], {"best_rank": it["rank"], "hot": it.get("hot", "")})
                if it["rank"] < b["best_rank"]:
                    b["best_rank"], b["hot"] = it["rank"], it.get("hot", "")
    rows = []
    for x in topics.values():
        boards = x["boards"]
        # 微博/头条有两个接口，按平台计数时合并
        platforms = {re.sub(r"（官方接口）$", "", n) for n in boards}
        title = x["title"]
        w, r = hits(title, WALLET), hits(title, REDLINE)
        rows.append({
            "title": title, "url": x["url"], "first_seen": x["first_seen"], "last_seen": x["last_seen"],
            "snapshots": len(x["seen"]), "platforms": len(platforms),
            "best_rank": min(b["best_rank"] for b in boards.values()),
            "boards": {n: b["best_rank"] for n, b in boards.items()},
            "category": category(title), "wallet_words": w, "redline_words": r,
        })
    rows.sort(key=lambda r: (-r["platforms"], -r["snapshots"], r["best_rank"]))
    return rows, health


def is_wallet(r):
    if not r["wallet_words"] or r["redline_words"]:
        return False
    # 只命中“AI”“价”这类泛词又属于文娱体育的，剔除
    if r["category"] == "文娱体育" and len(r["wallet_words"]) < 2:
        return False
    return True


def heat(r):
    return "高" if r["platforms"] >= 3 or r["snapshots"] >= 8 else ("中" if r["platforms"] >= 2 or r["snapshots"] >= 3 else "低")


def table(rows, extra=False):
    out = ["| # | 标题 | 热度 | 平台数 | 在榜次数 | 最高排名 | 首次—最后 | 平台(排名) |" + (" 命中词 |" if extra else ""),
           "|---|---|---|---|---|---|---|---|" + ("---|" if extra else "")]
    for i, r in enumerate(rows, 1):
        t = r["title"].replace("|", "｜")
        b = "、".join(f"{n}{k}" for n, k in r["boards"].items())
        line = (f"| {i} | [{t}]({r['url']}) | {heat(r)} | {r['platforms']} | {r['snapshots']} | {r['best_rank']} | "
                f"{r['first_seen']}—{r['last_seen']} | {b} |")
        if extra:
            line += " " + "、".join(r["wallet_words"][:5]) + " |"
        out.append(line)
    return out


def write(label, snaps, rows, health, outdir):
    os.makedirs(outdir, exist_ok=True)
    head = [f"时间范围：{label}；快照 {len(snaps)} 次（" + "、".join(t.strftime("%H:%M") for t, _ in snaps) + "）",
            "", "热度：高＝3个及以上平台或在榜8次以上；中＝2个平台或在榜3次以上；其余为低。", ""]
    bad = [f"{n}（失败{h['fail']}次：{h['last_error'][:50]}）" for n, h in health.items() if h["fail"]]
    head += ["来源健康：" + (("；".join(bad)) if bad else f"{len(health)} 个来源全部正常"), ""]

    wallet = [r for r in rows if is_wallet(r)]
    w = [f"# 钱包线索 {label}", ""] + head + [
        f"共 {len(rows)} 个去重标题，其中钱包相关 {len(wallet)} 个（关键词粗筛，宁多勿漏；**全部未核实**）。", ""]
    w += table(wallet, extra=True)
    with open(os.path.join(outdir, f"{label}_钱包线索.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(w) + "\n")

    n = [f"# 新闻汇总 {label}", ""] + head + [f"共 {len(rows)} 个去重标题。", "",
                                             "## 重点（2个及以上平台，或在榜3次以上）", ""]
    key_rows = [r for r in rows if r["platforms"] >= 2 or r["snapshots"] >= 3]
    n += table(key_rows)
    order = ["时政国际", "财经资产", "民生消费", "社会其他", "科技数码", "文娱体育", "灾难事故"]
    for c in order:
        cr = [r for r in rows if r["category"] == c]
        if cr:
            n += ["", f"## {c}（{len(cr)}）", ""] + table(cr)
    with open(os.path.join(outdir, f"{label}_新闻汇总.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(n) + "\n")
    with open(os.path.join(outdir, f"{label}_全部.json"), "w", encoding="utf-8") as f:
        json.dump({"label": label, "snapshots": [t.isoformat() for t, _ in snaps], "health": health,
                   "topics": rows}, f, ensure_ascii=False)
    return len(rows), len(wallet)


def prune():
    cutoff = (datetime.now(BJ) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    for d in glob.glob(os.path.join(ROOT, "data", "????-??-??")):
        if os.path.basename(d) < cutoff:
            shutil.rmtree(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="北京时间日期 YYYY-MM-DD，整天")
    ap.add_argument("--last", type=int, help="截至现在的过去 N 小时")
    ap.add_argument("--out", default=os.path.join(ROOT, "reports"))
    a = ap.parse_args()
    now = datetime.now(BJ)
    if a.last:
        start, end = now - timedelta(hours=a.last), now + timedelta(minutes=1)
        label = f"{start:%m%d-%H%M}至{now:%m%d-%H%M}"
    else:
        day = a.date or now.strftime("%Y-%m-%d")
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=BJ)
        end, label = start + timedelta(days=1), day
    snaps = snapshots(start, end)
    if not snaps:
        print("这段时间没有快照")
        return
    rows, health = merge(snaps)
    total, wallet = write(label, snaps, rows, health, a.out)
    print(f"{label}: {len(snaps)} 次快照，{total} 个去重标题，钱包线索 {wallet} 个 → {a.out}")
    prune()


if __name__ == "__main__":
    main()
