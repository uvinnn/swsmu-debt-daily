#!/usr/bin/env bash
# 收蛋·快速通道 —— 一次调用完成「网络预检 → 按需同步 → 抓数 → 打印口播文案」
#
# 用法：
#   bash run_now.sh          立刻出结果，数据没出也不等（约 5~10 秒）
#   bash run_now.sh --wait   数据没出就一直等，每 3 分钟重抓，21:45 截止
#
# 设计要点（都是为了"快"）：
#   * 网络预检最多 3 秒，github 不通就直接跳过同步，绝不空等
#   * git pull 用 20 秒硬超时 + 低速熔断，网慢也不会卡死
#   * --copy-only 不落盘 egg-data.json，工作区保持干净 → 下次同步不会被脏文件阻塞
#   * 不碰 git push / GitHub API（网络不通时这两样最容易长时间挂住）
cd "$(dirname "$0")" || exit 1

WAIT=0
[ "$1" = "--wait" ] && WAIT=1

# ── 1) 网络预检 + 按需同步 ────────────────────────────────────────────
if curl -s -o /dev/null --max-time 3 https://github.com; then
  if /usr/bin/timeout 20 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=8 \
       pull --ff-only -q >/dev/null 2>&1; then
    echo "[已同步 $(git log --oneline -1 | cut -c1-8)]"
  else
    echo "[同步跳过（网络慢或本地有改动）]"
  fi
else
  echo "[跳过同步（github 不通）]"
fi

# ── 2) 抓数 + 出文案（数据没出时按需重试）─────────────────────────────
while :; do
  OUT=$(python swsmu_debt_daily.py --copy-only 2>&1)
  RC=$?

  if echo "$OUT" | grep -q "💡"; then
    echo "$OUT" | grep -E "净值日期:|两个数据源均无|未找到数据|净值未出" | head -5
    echo "---------- 口播文案 ----------"
    echo "$OUT" | sed -n '/💡/,/💖/p'
    exit 0
  fi

  # 非交易日 / 其他情况：如实回报，不重试
  if [ "$RC" != "2" ]; then
    echo "$OUT" | tail -6
    exit "$RC"
  fi

  # RC=2 = 当日净值还没出
  if [ "$WAIT" = "0" ] || [ "$(date +%H%M)" -ge 2145 ]; then
    echo "$OUT" | tail -3
    echo "（未生成文案：当日净值尚未更新）"
    exit 2
  fi
  echo "$(date '+%H:%M:%S') 净值未出，180 秒后重试（截止 21:45）"
  sleep 180
done
