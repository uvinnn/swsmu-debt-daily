#!/usr/bin/env python3
"""
申万菱信债基每日收蛋文案自动生成器
数据来源：天天基金公开 API（https://fund.eastmoney.com）
部署环境：GitHub Actions（每天 20:00 北京时间自动运行）
推送渠道：钉钉群机器人 + egg-data.json（供 H5 页面读取）
"""

import re
import json
import sys
import os
import time
import hmac
import hashlib
import base64
import urllib.request
import urllib.parse
from datetime import datetime, date

# ============================================================
# 配置
# ============================================================

# 目标产品列表（同蛋数时按 sort_order 升序排列）
# 排序规则：蛋数高→低，同蛋数主推产品优先，然后非主推
# 主推4只顺序：稳鑫30天A → 稳鑫60天A → 稳鑫90天A → 申万菱信季季瑞A
TARGET_FUNDS = [
    ("015489", "稳鑫30天A", True, 1),
    ("016748", "稳鑫60天A", True, 2),
    ("015923", "稳鑫90天A", True, 3),
    ("022061", "申万菱信季季瑞A", True, 4),
    ("007240", "安泰瑞利C", False, 5),
    ("011986", "申万菱信合利C", False, 6),
    ("005990", "安泰惠利C", False, 7),
    ("019046", "安泰裕利C", False, 8),
]

# 天天基金 API
API_URL = (
    "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"
    "?t=1&lx=1&letter=&gsid=80045188&sort=zdf,desc&page=1,200"
)

# 文案模板
TEMPLATE = """💡闲钱理财债短情长，小顾家的债基今天也来给大家加加油！

{product_list}

📚讨论区活动福利多多，小伙伴们关注起来！
💖欢迎大家持续关注~"""

# 钉钉机器人配置（从环境变量读取）
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.environ.get("DINGTALK_SECRET", "")

# egg-data.json 路径
EGG_DATA_PATH = "egg-data.json"


def fetch_fund_data():
    """从天天基金 API 抓取申万菱信全部基金净值数据。"""
    req = urllib.request.Request(API_URL, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://fund.eastmoney.com/",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("gbk", errors="replace")

    # 提取 showday 数组
    showday = []
    sd_match = re.search(r'showday:\s*(\[[^\]]+\])', raw)
    if sd_match:
        showday = eval(sd_match.group(1))

    # 提取 datas 数组
    datas = []
    datas_start = raw.index('datas:[') + len('datas:')
    depth = 0
    datas_end = datas_start
    for i in range(datas_start, len(raw)):
        c = raw[i]
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                datas_end = i + 1
                break

    datas_str = raw[datas_start:datas_end]

    row_pattern = re.compile(r'\[([^\]]*(?:\[[^\]]*\][^\]]*)*)\]')
    for m in row_pattern.finditer(datas_str):
        row_str = m.group(1)
        fields = []
        i = 0
        while i < len(row_str):
            while i < len(row_str) and row_str[i] in ' \t\n\r':
                i += 1
            if i >= len(row_str):
                break
            if row_str[i] == '"':
                j = i + 1
                while j < len(row_str):
                    if row_str[j] == '\\':
                        j += 2
                    elif row_str[j] == '"':
                        break
                    else:
                        j += 1
                fields.append(row_str[i+1:j])
                i = j + 1
            elif row_str[i] == ',':
                fields.append('')
                i += 1
            else:
                j = i
                while j < len(row_str) and row_str[j] != ',':
                    j += 1
                val = row_str[i:j].strip()
                if val == '':
                    fields.append('')
                else:
                    fields.append(val)
                i = j
            while i < len(row_str) and row_str[i] == ',':
                i += 1
        if fields:
            datas.append(fields)

    return datas, showday


def parse_egg_count(growth_rate_str):
    """将日增长率字符串转换为收蛋数（1bp = 1蛋）"""
    try:
        rate = float(growth_rate_str)
    except (ValueError, TypeError):
        return 0
    return int(round(rate * 100))


def build_copy(egg_results):
    """生成最终文案，按蛋数从高到低，同蛋数按 sort_order"""
    egg_results.sort(key=lambda x: (-x["egg"], x["sort_order"]))

    lines = []
    for item in egg_results:
        lines.append(f"【{item['name']}】收{item['egg']}蛋；")

    return TEMPLATE.format(product_list="\n".join(lines))


def send_dingtalk(text):
    """通过钉钉群机器人发送消息（加签模式）"""
    if not DINGTALK_WEBHOOK or not DINGTALK_SECRET:
        print("⚠️ 未配置钉钉 Webhook，跳过推送")
        return False

    timestamp = str(round(time.time() * 1000))
    secret_enc = DINGTALK_SECRET.encode('utf-8')
    string_to_sign = f'{timestamp}\n{DINGTALK_SECRET}'
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))

    url = f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"

    data = json.dumps({
        "msgtype": "text",
        "text": {"content": text}
    }).encode('utf-8')

    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        if result.get("errcode") == 0:
            print("✅ 钉钉推送成功")
            return True
        else:
            print(f"❌ 钉钉推送失败: {result}")
            return False


def update_egg_data(egg_results, nav_date, copy_text):
    """更新 egg-data.json（历史累积格式，H5 页面读取）"""
    today_str = date.today().strftime("%Y-%m-%d")

    # 排序后构建当日记录
    sorted_results = sorted(egg_results, key=lambda x: (-x["egg"], x["sort_order"]))
    total_eggs = sum(r["egg"] for r in sorted_results if r["egg"] > 0)

    today_record = {
        "date": today_str,
        "nav_date": nav_date,
        "total": total_eggs,
        "results": [
            {
                "code": r["code"],
                "name": r["name"],
                "eggs": r["egg"],
                "change": f"{'+' if r['growth_rate'] and float(r['growth_rate']) > 0 else ''}{r['growth_rate']}%"
            }
            for r in sorted_results
        ],
        "copy": copy_text
    }

    # 读取现有数据
    existing = {"records": []}
    if os.path.exists(EGG_DATA_PATH):
        try:
            with open(EGG_DATA_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {"records": []}

    records = existing.get("records", [])

    # 替换同一天的数据，否则插入
    replaced = False
    for i, rec in enumerate(records):
        if rec.get("date") == today_str:
            records[i] = today_record
            replaced = True
            break
    if not replaced:
        records.insert(0, today_record)

    # 按日期降序，保留最多 90 天
    records.sort(key=lambda r: r.get("date", ""), reverse=True)
    records = records[:90]

    with open(EGG_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump({"records": records}, f, ensure_ascii=False, indent=2)

    print(f"✅ egg-data.json 已更新（共 {len(records)} 条记录）")


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始抓取基金净值数据...")

    all_data, showday = fetch_fund_data()
    print(f"  获取到 {len(all_data)} 条基金数据")
    print(f"  净值日期: {showday}")

    latest_nav_date = showday[0] if showday else "未知"
    today_str = date.today().strftime("%Y-%m-%d")

    egg_results = []
    missing = []

    for code, name, is_priority, sort_order in TARGET_FUNDS:
        found = None
        for row in all_data:
            if len(row) > 0 and row[0] == code:
                found = row
                break

        if not found:
            missing.append(f"{code} {name}")
            print(f"  ⚠️ {code} {name}: 未找到数据")
            continue

        growth_rate = found[8] if len(found) > 8 else "0"
        egg = parse_egg_count(growth_rate)

        egg_results.append({
            "code": code,
            "name": name,
            "egg": egg,
            "is_priority": is_priority,
            "sort_order": sort_order,
            "growth_rate": growth_rate,
            "nav_date": latest_nav_date,
        })

        print(f"  {code} {name}: {growth_rate}% → {egg}蛋")

    if missing:
        print(f"\n⚠️ 以下产品未找到数据: {', '.join(missing)}")
        if len(missing) > 2:
            print("❌ 缺失数据过多，本次不生成文案")
            send_dingtalk(f"❌ 债基数据抓取失败\n缺失数据过多: {', '.join(missing)}\n请手动检查。")
            sys.exit(1)

    # 净值日期检查
    if today_str not in latest_nav_date:
        print(f"⚠️ 净值日期({latest_nav_date})不是今天({today_str})，数据可能尚未更新")
        sys.exit(2)

    # 生成文案
    copy = build_copy(egg_results)

    print("\n" + "=" * 50)
    print(copy)
    print("=" * 50)

    # 1. 推送到钉钉
    send_dingtalk(copy)

    # 2. 更新 egg-data.json（H5 页面数据源）
    update_egg_data(egg_results, latest_nav_date, copy)


if __name__ == "__main__":
    main()
