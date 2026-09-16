#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修复 egg-data.json 里 change 字段的双符号脏数据（--0.02% / +-0.01% 等）。

背景：老版本脚本无条件拼接正负号前缀，导致 '--0.02%' 这种双符号；
H5（egg-tracker.html）用 parseFloat(change) 判定涨跌配色，遇到它会得到 NaN，
跌的那天显示成灰色。

用法：
    python fix_change_format.py           # dry-run，只打印将要修改的条目
    python fix_change_format.py --apply   # 实际写回 egg-data.json

同时会校验 change 与 eggs 是否一致（1bp = 1蛋），不一致只报告、不自动改蛋数。
"""

import json
import sys

from swsmu_debt_daily import format_change, EGG_DATA_PATH


def main():
    apply = "--apply" in sys.argv

    with open(EGG_DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    changed = []
    mismatch = []

    for rec in data.get("records", []):
        nav_date = rec.get("nav_date")
        for item in rec.get("results", []):
            old = item.get("change", "")
            new = format_change(old)
            if old != new:
                changed.append((nav_date, item.get("name"), old, new))
                if apply:
                    item["change"] = new

            # 一致性校验：蛋数应等于 round(涨跌幅% * 100)
            try:
                pct = float(new.replace("%", ""))
            except ValueError:
                pct = None
            if pct is not None and item.get("eggs") is not None:
                if int(round(pct * 100)) != int(item["eggs"]):
                    mismatch.append((nav_date, item.get("name"), new, item["eggs"]))

    print(f"待规范化 {len(changed)} 条：")
    for c in changed[:40]:
        print(f"  {c[0]} {c[1]}: {c[2]} -> {c[3]}")
    if len(changed) > 40:
        print(f"  ...（共 {len(changed)} 条）")

    if mismatch:
        print(f"\n⚠️ change 与 eggs 不一致 {len(mismatch)} 条（未自动修改）：")
        for m in mismatch[:30]:
            print(f"  {m[0]} {m[1]}: change={m[2]} eggs={m[3]}")
    else:
        print("\n✅ change 与 eggs 全部一致")

    if apply:
        with open(EGG_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 已写回 {EGG_DATA_PATH}")
    else:
        print("\n（dry-run，未写文件。加 --apply 生效）")


if __name__ == "__main__":
    main()
