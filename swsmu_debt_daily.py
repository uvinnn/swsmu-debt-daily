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


def fetch_latest_growth(code):
    """
    备用数据源：从天天基金「单只基金历史净值」接口取最新一日增长率。
    用途：批量接口对部分产品（如暂停申购的 019046）不返回当日净值字段，
          直接用会误判成 0 蛋，这里兜底补齐。
    返回 (净值日期, 日增长率字符串)，取不到返回 (None, None)
    """
    url = (f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}"
           f"&pageIndex=1&pageSize=5&callback=cb")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "http://fund.eastmoney.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            txt = resp.read().decode("utf-8", "replace").strip()
        if txt.startswith("cb("):
            txt = txt[3:]
        if txt.endswith(")"):
            txt = txt[:-1]
        lst = json.loads(txt)["Data"]["LSJZList"]
        if lst:
            return lst[0].get("FSRQ"), lst[0].get("JZZZL")
    except Exception as e:
        print(f"    备用接口异常: {e}")
    return None, None


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


def already_pushed_today(nav_date):
    """
    判断今天这份净值数据是否已经推送过（避免同一天重复发钉钉）。
    判定条件：egg-data.json 中已存在 date=今天 且 nav_date 相同的记录。
    设置环境变量 FORCE_PUSH=1 可强制再次推送。
    """
    if os.environ.get("FORCE_PUSH") == "1":
        return False
    if not os.path.exists(EGG_DATA_PATH):
        return False
    try:
        with open(EGG_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False

    today_str = date.today().strftime("%Y-%m-%d")
    for rec in data.get("records", []):
        if rec.get("date") == today_str and rec.get("nav_date") == nav_date:
            return True
    return False


def update_egg_data(egg_results, nav_date, copy_text, no_nav=None):
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

    # 记录"净值未出、未纳入文案"的产品，留痕备查（绝不按 0 蛋计入）
    if no_nav:
        today_record["no_nav"] = no_nav

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


def is_trading_day(check_date):
    """
    判断是否为A股交易日。
    - 周六/周日直接返回 False
    - 其余通过 timor.club 节假日 API 确认是否为节假日
    - API 不可用时，回退到仅跳过周末（宁可多发不漏发）
    """
    # 先排除周末
    if check_date.weekday() >= 5:  # 5=周六, 6=周日
        return False

    # 查询节假日 API（timor.club，免费，无需 key）
    try:
        date_str = check_date.strftime("%Y%m%d")
        url = f"https://timor.tech/api/holiday/info/{date_str}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # type: 0=工作日, 1=周末, 2=节假日, 3=调休（本是休息日但需上班）
        day_type = data.get("type", {}).get("type")
        if day_type == 3:
            # 调休工作日（本是周末但要上班），债基正常交易
            return True
        if day_type in (1, 2):
            # 周末或法定节假日
            return False
        # type==0 或 API 返回异常，视为工作日
        return True
    except Exception as e:
        print(f"  ⚠️ 节假日 API 查询失败 ({e})，按工作日处理")
        return True


def main():
    today = date.today()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始抓取基金净值数据...")

    # 非交易日直接退出（不发钉钉，不更新数据）
    if not is_trading_day(today):
        weekday_name = ["周一","周二","周三","周四","周五","周六","周日"][today.weekday()]
        print(f"📅 今天是 {today.strftime('%Y-%m-%d')} {weekday_name}，非交易日，跳过执行。")
        sys.exit(0)

    all_data, showday = fetch_fund_data()
    print(f"  获取到 {len(all_data)} 条基金数据")
    print(f"  净值日期: {showday}")

    latest_nav_date = showday[0] if showday else "未知"
    today_str = today.strftime("%Y-%m-%d")

    egg_results = []
    missing = []      # 数据源里完全找不到该产品
    no_nav = []       # 产品存在，但拿不到当日净值（真实收益未知，绝不能按 0 蛋算）

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

        # 批量接口当日字段为空（常见于暂停申购产品）→ 用单只净值接口兜底补齐
        if not str(growth_rate).strip():
            f_date, f_rate = fetch_latest_growth(code)
            if f_date == latest_nav_date and str(f_rate).strip() not in ("", "None"):
                growth_rate = f_rate
                print(f"    ↳ 批量接口无当日数据，备用接口补齐：{f_date} {f_rate}%")
            else:
                # 两个数据源都没有当日净值 → 真实收益未知，绝不臆造为 0 蛋，直接剔除并上报
                no_nav.append(f"{name}（{code}）")
                print(f"  ⚠️ {code} {name}: 两个数据源均无 {latest_nav_date} 的净值，"
                      f"真实收益未知，不参与今日文案（备用接口最新 {f_date}）")
                continue

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
        print(f"\n⚠️ 数据源中未找到以下产品: {', '.join(missing)}")

    if no_nav:
        print(f"\n⚠️ 以下产品今日({latest_nav_date})净值未出，真实收益未知，已从文案中剔除: {', '.join(no_nav)}")

    # 缺失过多（找不到 + 净值未出）视为抓取失败，不生成文案
    if len(missing) + len(no_nav) > 2:
        detail = []
        if missing:
            detail.append("数据源缺失: " + ", ".join(missing))
        if no_nav:
            detail.append("净值未出: " + ", ".join(no_nav))
        print("❌ 缺失数据过多，本次不生成文案")
        send_dingtalk("❌ 债基数据抓取失败\n" + "\n".join(detail) + "\n请手动检查。")
        sys.exit(1)

    # 净值日期检查
    if today_str not in latest_nav_date:
        print(f"⚠️ 净值日期({latest_nav_date})不是今天({today_str})，数据可能尚未更新")
        sys.exit(2)

    # 生成文案（只用确认拿到当日净值的产品）
    copy = build_copy(egg_results)

    print("\n" + "=" * 50)
    print(copy)
    print("=" * 50)

    # 钉钉正文：有产品净值未出时，明确写出来，绝不静默略过
    ding_text = copy
    if no_nav:
        ding_text += ("\n\n⚠️ 注意：以下产品今日净值未公布，真实收益未知，"
                      "已从上面的收蛋文案中剔除（非 0 蛋）：\n" + "、".join(no_nav))

    # 1. 推送到钉钉（同一天同一份净值只推一次，避免重复打扰）
    if already_pushed_today(latest_nav_date) and not no_nav:
        print("⏭️ 今日该净值已推送过钉钉，跳过推送（如需强制推送请设 FORCE_PUSH=1）")
    else:
        send_dingtalk(ding_text)

    # 2. 更新 egg-data.json（H5 页面数据源，只写确认有净值的产品）
    update_egg_data(egg_results, latest_nav_date, copy, no_nav=no_nav)


def run_with_retry():
    """
    内置重试模式：从调用时刻起，每 5 分钟重试一次，直到成功或 20:30 截止。
    - exit code=0：成功，退出
    - exit code=2：净值未更新，等待重试
    - 其他 exit code：脚本异常，直接退出
    截止后仍失败则发钉钉告警并退出（exit code=3）
    """
    retry_interval = 300

    attempt = 0
    while True:
        attempt += 1
        now = datetime.now()
        print(f"\n[重试模式] === 第 {attempt} 次尝试 {now.strftime('%Y-%m-%d %H:%M:%S')} ===")

        code = 0
        try:
            main()
        except SystemExit as e:
            code = e.code if e.code is not None else 1
        except Exception as e:
            print(f"[重试模式] ❌ 脚本异常: {e}")
            sys.exit(1)

        if code == 0:
            print("[重试模式] ✅ 成功！")
            sys.exit(0)
        elif code == 2:
            cutoff = now.replace(hour=20, minute=30, second=0, microsecond=0)
            if now > cutoff:
                print("[重试模式] ⏰ 已到 20:30 截止，放弃重试")
                send_dingtalk("⚠️ 今晚净值数据延迟更新，截至20:30尚未获取到今日数据，请手动检查。")
                sys.exit(3)
            print(f"[重试模式] ⏳ 净值未更新，{retry_interval}秒后重试（截止 20:30）...")
            time.sleep(retry_interval)
        else:
            print(f"[重试模式] ❌ 脚本异常退出 (exit code: {code})")
            sys.exit(code)


if __name__ == "__main__":
    if "--with-retry" in sys.argv:
        run_with_retry()
    else:
        main()
