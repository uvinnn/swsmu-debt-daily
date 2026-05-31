#!/usr/bin/env python3
"""
申万菱信债基每日收蛋文案自动生成器
数据来源：天天基金公开 API（https://fund.eastmoney.com）
触发时间：每天 20:00，失败重试至 20:30
"""

import re
import json
import sys
import os
import time
import urllib.request
from datetime import datetime, date

# ============================================================
# 配置
# ============================================================

# 目标产品列表（同蛋数时按下表顺序排列，即 sort_order 升序）
# 依据用户2026-05-28提供的文案示例确定顺序
TARGET_FUNDS = [
    ("022061", "申万菱信季季瑞A", True, 1),
    ("015489", "稳鑫30天A", True, 2),
    ("011986", "申万菱信合利C", False, 3),
    ("005990", "安泰惠利C", False, 4),
    ("007240", "安泰瑞利C", False, 5),
    ("016748", "稳鑫60天A", True, 6),
    ("015923", "稳鑫90天A", True, 7),
    ("019046", "安泰裕利C", False, 8),
]

# 天天基金 API（申万菱信基金公司代码：80045188）
API_URL = (
    "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"
    "?t=1&lx=1&letter=&gsid=80045188&sort=zdf,desc&page=1,200"
)

# 文案模板
TEMPLATE = """💡闲钱理财债短情长，小顾家的债基今天也来给大家加加油！

{product_list}

📚讨论区活动福利多多，小伙伴们关注起来！
💖欢迎大家持续关注~"""

# 输出目录
OUTPUT_DIR = r"C:\Users\admin\WorkBuddy\2026-05-28-21-29-18\.workbuddy\output"


def fetch_fund_data():
    """
    从天天基金 API 抓取申万菱信全部基金净值数据。
    返回 (datas_list, showday_list)
    API 返回格式：var db={datas:[...], showday:[...], ...}
    datas 中每行结构: [代码, 名称, 拼音, 净值, 累计净值, 前日净值, 前日累计净值, 日增长额, 日增长率%, ...]
    """
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

    # 提取 datas 数组 —— 找到 "datas:[" 然后手动解析每行
    datas = []
    datas_start = raw.index('datas:[') + len('datas:')
    # 找到 datas 数组的结束位置
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

    # 用正则提取每行数组（每行以 [ 开头，] 结尾）
    row_pattern = re.compile(r'\[([^\]]*(?:\[[^\]]*\][^\]]*)*)\]')
    for m in row_pattern.finditer(datas_str):
        row_str = m.group(1)
        # 解析 CSV 风格的字段（引号包裹的字符串和数字）
        fields = []
        i = 0
        while i < len(row_str):
            # 跳过空白
            while i < len(row_str) and row_str[i] in ' \t\n\r':
                i += 1
            if i >= len(row_str):
                break
            if row_str[i] == '"':
                # 引号包裹的字符串
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
                # 非引号字段
                j = i
                while j < len(row_str) and row_str[j] != ',':
                    j += 1
                val = row_str[i:j].strip()
                if val == '':
                    fields.append('')
                else:
                    fields.append(val)
                i = j
            # 跳过逗号
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
    return int(round(rate * 100))  # 例如 0.02% → 2 蛋


def build_copy(egg_results):
    """根据收蛋结果生成最终文案，按蛋数从高到低，同蛋数按固定展示顺序"""
    egg_results.sort(key=lambda x: (-x["egg"], x["sort_order"]))

    lines = []
    for item in egg_results:
        lines.append(f"【{item['name']}】收{item['egg']}蛋；")

    return TEMPLATE.format(product_list="\n".join(lines))


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始抓取基金净值数据...")

    all_data, showday = fetch_fund_data()
    print(f"  获取到 {len(all_data)} 条基金数据")
    print(f"  净值日期: {showday}")

    # 用 showday[0] 作为最新净值日期
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

        growth_rate = found[8] if len(found) > 8 else "0"  # 字段索引 8 = 日增长率
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

    # 缺失数据检查
    if missing:
        print(f"\n⚠️ 以下产品未找到数据: {', '.join(missing)}")
        if len(missing) > 2:
            print("❌ 缺失数据过多，本次不生成文案")
            sys.exit(1)

    # 净值日期检查：如果不是今天的数据，认为还未更新，退出重试
    if today_str not in latest_nav_date:
        print(f"⚠️ 净值日期({latest_nav_date})不是今天({today_str})，数据可能尚未更新")
        sys.exit(2)

    # 生成文案
    copy = build_copy(egg_results)

    print("\n" + "=" * 50)
    print(copy)
    print("=" * 50)

    # 保存结果文件
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    output_path = os.path.join(OUTPUT_DIR, "swsmu_daily_copy.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(copy)
    print(f"\n✅ 文案已保存到: {output_path}")

    json_path = os.path.join(OUTPUT_DIR, "swsmu_daily_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": today_str,
            "nav_date": latest_nav_date,
            "results": egg_results,
            "copy": copy,
        }, f, ensure_ascii=False, indent=2)
    print(f"✅ 数据已保存到: {json_path}")


def run_with_retry():
    """
    内置重试模式：从调用时刻起，每 5 分钟重试一次，直到成功或 20:30 截止。
    - exit code=0：成功，退出
    - exit code=2：净值未更新，等待重试
    - 其他 exit code：脚本异常，直接退出
    截止后仍失败则发钉钉告警并退出（exit code=3）
    """
    import subprocess

    python_exe = sys.executable
    script_path = os.path.abspath(__file__)
    retry_interval = 300  # 5 分钟

    attempt = 0
    while True:
        attempt += 1
        now = datetime.now()
        print(f"\n[重试模式] === 第 {attempt} 次尝试 {now.strftime('%Y-%m-%d %H:%M:%S')} ===")

        result = subprocess.run(
            [python_exe, script_path],
            capture_output=False
        )
        code = result.returncode

        if code == 0:
            print("[重试模式] ✅ 成功！")
            sys.exit(0)
        elif code == 2:
            # 计算截止时间（当天 20:30）
            cutoff = now.replace(hour=20, minute=30, second=0, microsecond=0)

            if now > cutoff:
                print(f"[重试模式] ⏰ 已到 20:30 截止，放弃重试")
                _send_dingtalk_warning()
                sys.exit(3)

            wait_secs = retry_interval
            print(f"[重试模式] ⏳ 净值未更新，{wait_secs}秒后重试（截止 20:30）...")
            time.sleep(wait_secs)
        else:
            print(f"[重试模式] ❌ 脚本异常退出 (exit code: {code})")
            sys.exit(code)


def _send_dingtalk_warning():
    """发送钉钉告警：净值延迟"""
    try:
        import hmac
        import hashlib
        import base64
        import urllib.parse

        webhook = os.environ.get("DINGTALK_WEBHOOK", "")
        secret = os.environ.get("DINGTALK_SECRET", "")
        if not webhook:
            print("[告警] 未配置 DINGTALK_WEBHOOK，跳过钉钉通知")
            return

        timestamp = str(round(time.time() * 1000))
        msg = f"{timestamp}\n{secret}"
        sign = urllib.parse.quote_plus(
            base64.b64encode(
                hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
            )
        )
        url = f"{webhook}&timestamp={timestamp}&sign={sign}"
        body = json.dumps({
            "msgtype": "text",
            "text": {"content": "⚠️ 今晚净值数据延迟更新，截至20:30尚未获取到今日数据，请手动检查。"}
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[告警] 钉钉通知已发送: {resp.status}")
    except Exception as e:
        print(f"[告警] 发送钉钉通知失败: {e}")


if __name__ == "__main__":
    if "--with-retry" in sys.argv:
        run_with_retry()
    else:
        main()
