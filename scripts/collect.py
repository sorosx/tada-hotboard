#!/usr/bin/env python3
"""泰达的账本 · 热榜快照采集

每次运行抓取一次国内主要热榜，存成
  data/YYYY-MM-DD/HHMM.json   （北京时间）
只用 Python 标准库，GitHub Actions 上无需安装任何依赖。

数据接口参考开源项目 yiktt/hotboard（MIT）：
  - Codelife 第三方聚合接口：大部分平台
  - 平台官方公开接口：新浪热榜、网易、澎湃、中新网 RSS，以及微博、头条的备用接口
"""
import glob
import gzip
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# id, 名称, codelife 榜单 ID
CODELIFE = [
    ("weibo",        "微博热搜",       "KqndgxeLl9"),
    ("zhihu",        "知乎热榜",       "mproPpoq6O"),
    ("baidu",        "百度热点",       "Jb0vmloB1G"),
    ("toutiao",      "头条热榜",       "toutiao"),
    ("wechat",       "微信热文",       "WnBe01o371"),
    ("douyin",       "抖音热点",       "DpQvNABoNE"),
    ("kuaishou",     "快手热榜",       "MZd7PrPerO"),
    ("tieba",        "百度贴吧",       "Om4ejxvxEN"),
    ("smzdm",        "什么值得买",     "K7GdagpoQy"),
    ("txnews",       "腾讯新闻·热问",  "12owgX0oNV"),
    ("sinafinance",  "新浪财经·点击排行", "rx9ozj7oXb"),
    ("yicai",        "第一财经·周榜",  "0MdKam4ow1"),
    ("wallstreetcn", "华尔街见闻",     "G2me3ndwjq"),
    ("xueqiu",       "雪球",           "X12owXzvNV"),
    ("ithome",       "IT之家",         "74Kvx59dkx"),
    ("kr36",         "36氪",           "Q1Vd5Ko85R"),
    ("huxiu",        "虎嗅",           "5VaobgvAj1"),
]


def get(url, timeout=20, accept="application/json, text/plain, */*", referer=None):
    headers = {"User-Agent": UA, "Accept": accept, "Accept-Language": "zh-CN,zh;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def norm(items):
    out = []
    for i, it in enumerate(items, 1):
        t = clean(it.get("title"))
        if not t:
            continue
        out.append({"rank": len(out) + 1, "title": t,
                    "url": clean(it.get("url")), "hot": clean(it.get("hot"))})
    return out


def codelife(cid):
    j = json.loads(get(f"https://api.codelife.cc/api/top/list?lang=cn&id={cid}&_={int(time.time()*1000)}"))
    if j.get("code") != 200 or not j.get("data"):
        raise ValueError(f"codelife 返回异常 code={j.get('code')}")
    return norm({"title": d.get("title"), "url": d.get("link"), "hot": d.get("hotValue")} for d in j["data"])


def sina_hot():
    day = datetime.now(BJ).strftime("%Y%m%d")
    txt = get("https://top.news.sina.com.cn/ws/GetTopDataList.php?top_type=day"
              f"&top_cat=www_www_all_suda_suda&top_time={day}&top_show_num=50&top_order=DESC&js_var=all_1_data",
              referer="https://news.sina.com.cn/")
    j = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
    return norm({"title": d.get("title"), "url": d.get("url"), "hot": d.get("top_num")} for d in j.get("data", []))


def netease():
    j = json.loads(get("https://m.163.com/fe/api/hot/news/flow", referer="https://m.163.com/"))
    return norm({"title": d.get("title"), "url": d.get("url")} for d in j["data"]["list"])


def thepaper():
    j = json.loads(get("https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar", referer="https://www.thepaper.cn/"))
    return norm({"title": d.get("name"),
                 "url": d.get("link") or f"https://www.thepaper.cn/newsDetail_forward_{d.get('contId')}"}
                for d in j["data"]["hotNews"])


def chinanews():
    xml = get("https://www.chinanews.com.cn/rss/scroll-news.xml", accept="application/rss+xml, text/xml, */*")
    root = ET.fromstring(xml.encode("utf-8"))
    items = []
    for n in root.iter("item"):
        items.append({"title": n.findtext("title"), "url": n.findtext("link"), "hot": n.findtext("pubDate")})
    return norm(items)


def weibo_official():
    j = json.loads(get("https://weibo.com/ajax/side/hotSearch", referer="https://weibo.com/"))
    return norm({"title": d.get("word") or d.get("note"),
                 "url": "https://s.weibo.com/weibo?q=" + urllib.request.quote("#" + (d.get("word") or "") + "#"),
                 "hot": d.get("num")} for d in j["data"]["realtime"])


def toutiao_official():
    j = json.loads(get("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc", referer="https://www.toutiao.com/"))
    return norm({"title": d.get("Title"), "url": d.get("Url"), "hot": d.get("HotValue")} for d in j["data"])


OFFICIAL = [
    ("sinahot",   "新浪热榜（日榜）", sina_hot),
    ("netease",   "网易新闻",         netease),
    ("thepaper",  "澎湃新闻",         thepaper),
    ("chinanews", "中国新闻网·即时",  chinanews),
    ("weibo_off", "微博热搜（官方接口）", weibo_official),
    ("toutiao_off", "头条热榜（官方接口）", toutiao_official),
]


def run(fn, *args):
    last = None
    for attempt in range(2):
        try:
            items = fn(*args)
            if items:
                return {"ok": True, "items": items}
            last = "空列表"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"[:200]
        time.sleep(2)
    return {"ok": False, "error": last, "items": []}


def main():
    now = datetime.now(BJ)
    day_dir = os.path.join(ROOT, "data", now.strftime("%Y-%m-%d"))
    # 工作流每小时触发两次以防 GitHub 跳过；同一个北京时间小时只存一份
    if glob.glob(os.path.join(day_dir, now.strftime("%H") + "??.json*")) and "--force" not in sys.argv:
        print(f"{now:%Y-%m-%d %H}点 已有快照，跳过")
        return
    snap = {"fetched_at": now.isoformat(timespec="seconds"), "sources": {}}
    for sid, name, cid in CODELIFE:
        snap["sources"][sid] = {"name": name, "via": "codelife", **run(codelife, cid)}
    for sid, name, fn in OFFICIAL:
        snap["sources"][sid] = {"name": name, "via": "official", **run(fn)}

    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, now.strftime("%H%M") + ".json.gz")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))

    ok = sum(1 for s in snap["sources"].values() if s["ok"])
    total = len(snap["sources"])
    n = sum(len(s["items"]) for s in snap["sources"].values())
    print(f"{path}: {ok}/{total} 个来源成功，共 {n} 条")
    for sid, s in snap["sources"].items():
        if not s["ok"]:
            print(f"  失败 {sid} {s['name']}: {s['error']}")
    # 一个来源都没成功时让工作流报错，方便发现问题
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
