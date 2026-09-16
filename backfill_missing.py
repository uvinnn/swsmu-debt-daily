#!/usr/bin/env python3
"""
历史数据回填工具（一次性）

背景：天天基金「批量接口」对部分产品（尤其暂停申购的 019046）不返回当日净值，
      老脚本把这当成 0 蛋写入 egg-data.json，或者直接把该产品丢了。
      本脚本用「单只基金历史净值接口」把这些数据补全，让 H5 追踪页的历史数据真实。

用法：python backfill_missing.py        （先 dry-run 预览）
      python backfill_missing.py --apply（真正写入）
"""

import json
import sys
import urllib.request
from datetime import date

import swsmu_debt_daily as m

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "http://fund.eastmoney.com/",
}


def fetch_history(code, pages=12, page_size=20):
    """拉取单只基金历史净值，返回 {日期: 日增长率}
    注意：该接口每页最多返回 20 条，pageSize 设再大也只给 20 条，只能翻页。
    """
    mapping = {}
    for page in range(1, pages + 1):
        url = (f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}"
               f"&pageIndex={page}&pageSize={page_size}&callback=cb")
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            txt = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace").strip()
            if txt.startswith("cb("):
                txt = txt[3:]
            if txt.endswith(")"):
                txt = txt[:-1]
            lst = json.loads(txt)["Data"]["LSJZList"]
        except Exception as e:
            print(f"  {code} 第{page}页失败: {e}")
            break
        if not lst:
            break
        for it in lst:
            mapping[it.get("FSRQ")] = it.get("JZZZL")
    return mapping


def fmt_change(rate):
    try:
        return f"{'+' if float(rate) > 0 else ''}{rate}%"
    except (TypeError, ValueError):
        return f"{rate}%"


def main():
    apply = "--apply" in sys.argv

    with open(m.EGG_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    records = data.get("records", [])

    print(f"读取 {len(records)} 条历史记录，开始拉取各产品净值历史...")
    hist = {}
    for code, name, _pri, _so in m.TARGET_FUNDS:
        hist[code] = fetch_history(code)
        print(f"  {code} {name}: {len(hist[code])} 个交易日")

    changes = []
    fixed_records = 0
    for rec in records:
        nav_date = rec.get("nav_date") or rec.get("date")
        results = rec.get("results", [])
        by_code = {r["code"]: r for r in results}
        touched = False
        no_nav = []

        # 1) 补齐缺失 / 增长率为空的条目
        for code, name, _pri, _so in m.TARGET_FUNDS:
            row = by_code.get(code)
            rate = hist[code].get(nav_date)
            empty = row is None or str(row.get("change", "")).replace("+", "").replace("%", "").strip() == ""
            if not empty:
                continue
            if rate is None or str(rate).strip() == "":
                if row is None:
                    no_nav.append(f"{name}（{code}）")
                else:
                    no_nav.append(f"{name}（{code}）")
                    results.remove(row)
                    touched = True
                continue
            egg = m.parse_egg_count(rate)
            if row is None:
                results.append({
                    "code": code, "name": name, "eggs": egg, "change": fmt_change(rate)
                })
                changes.append(f"{rec['date']} 补入 {name}: {rate}% → {egg}蛋")
            else:
                changes.append(f"{rec['date']} 修正 {name}: 空 → {rate}% → {egg}蛋")
                row["eggs"] = egg
                row["change"] = fmt_change(rate)
            touched = True

        if not touched:
            continue
        fixed_records += 1

        # 2) 重新排序 + 重算总蛋数 + 重排文案
        order = {code: so for code, _n, _p, so in m.TARGET_FUNDS}
        results.sort(key=lambda r: (-r["eggs"], order.get(r["code"], 99)))
        rec["total"] = sum(r["eggs"] for r in results if r["eggs"] > 0)
        rec["results"] = results
        if no_nav:
            rec["no_nav"] = no_nav
        else:
            rec.pop("no_nav", None)

        # 用当前模板重排文案
        egg_results = [{
            "code": r["code"], "name": r["name"], "egg": r["eggs"],
            "sort_order": order.get(r["code"], 99),
        } for r in results]
        rec["copy"] = m.build_copy(egg_results)

    print(f"\n共 {fixed_records} 条记录需要修正，{len(changes)} 处数据变动：")
    for c in changes[:60]:
        print("  -", c)
    if len(changes) > 60:
        print(f"  ... 还有 {len(changes) - 60} 处")

    if not apply:
        print("\n[预览模式] 未写入。确认无误后加 --apply 执行。")
        return

    with open(m.EGG_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已写入 {m.EGG_DATA_PATH}")


if __name__ == "__main__":
    main()
