from datetime import datetime
import os
import logging
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from db import MysqlAccess
import requests

load_dotenv()

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# c.ai 平台設定：透過 ETA 訊息發送 API 觸發 c.ai 事件，由 c.ai 腳本推播卡片到 LINE Bot
# 值取自 c.ai 機器人管理 > 進階 > 通知服務設定（測試用模擬環境，上線用發佈環境）
CAI_ETA_URL = os.getenv("CAI_ETA_URL", "")  # 通知服務設定的「服務 Url」，例如 https://cai-innoserve.gss.com.tw/eta
CAI_BOT_ID = os.getenv("CAI_BOT_ID")  # Subscription Id
CAI_SUBSCRIPTION_KEY = os.getenv("CAI_SUBSCRIPTION_KEY")  # 通知金鑰
CAI_EVENT_NAME = os.getenv("CAI_EVENT_NAME", "fall_detected")  # 需與 c.ai 設定的事件名稱一致
CAI_CHANNEL = os.getenv("CAI_CHANNEL", "")  # 只推播到特定頻道；留空則推到發佈設定勾選的所有頻道
CAI_TIMEOUT = float(os.getenv("CAI_TIMEOUT", 10))
USER_ID_TO_PUSH = os.getenv("LINE_USER_ID")  # 由 c.ai 推播卡片的對象
MONITORED_USER_ID = int(os.getenv("MONITORED_USER_ID", 1))

print("=" * 60)
print("🤖 c.ai 平台設定")
print(f"✅ ETA_URL: {CAI_ETA_URL}" if CAI_ETA_URL else "❌ ETA_URL 未設定")
print(f"✅ BOT_ID: {CAI_BOT_ID}" if CAI_BOT_ID else "❌ BOT_ID 未設定")
print("✅ SUBSCRIPTION_KEY: 已設定" if CAI_SUBSCRIPTION_KEY else "❌ SUBSCRIPTION_KEY 未設定")
print(f"✅ EVENT_NAME: {CAI_EVENT_NAME}")
print(f"✅ USER_ID: {USER_ID_TO_PUSH}" if USER_ID_TO_PUSH else "⚠️  USER_ID 未設定")
print(f"✅ 監控用户 ID: {MONITORED_USER_ID}")
print("=" * 60)

# 初始化數據庫
try:
    MysqlAccess.init_db()
    logger.info("✅ 數據庫已初始化")
except Exception as e:
    logger.warning(f"⚠️  數據庫初始化失敗: {e}（繼續運行）")


def cai_configured():
  return bool(CAI_ETA_URL and CAI_BOT_ID and CAI_SUBSCRIPTION_KEY)


def send_fall_event_to_cai(event_time, confidence, location):
  """透過 ETA「發送事件訊息」API 觸發 c.ai 事件，由 c.ai 腳本推播跌倒通報卡片到 LINE Bot

  規格：C.ai 對話服務平台規格文件 1.2.3「1-1 發送事件訊息」
  """
  url = f"{CAI_ETA_URL.rstrip('/')}/api/subscription/{CAI_BOT_ID}/event/multicast"
  headers = {
      "x-gss-event-subscription-key": CAI_SUBSCRIPTION_KEY,
      "x-gss-event-from": CAI_BOT_ID,
      "content-type": "application/json",
  }
  conversation = {
      "Id": "",  # Line 頻道留空
      "RecipientId": USER_ID_TO_PUSH,
      "Subject": "長者跌倒告警",
      "IsGroup": False,
  }
  if CAI_CHANNEL:
    conversation["ChannelList"] = {"InclusionChannels": CAI_CHANNEL}
  payload = {
      "TriggerId": CAI_BOT_ID,
      "Conversations": [conversation],
      "Event": {
          "Name": CAI_EVENT_NAME,
          # 對應 c.ai 跌倒通報卡片中的 {timestamp}、{location} 變數
          "Value": {
              "timestamp": event_time,
              "location": location,
              "confidence": confidence,
          },
      },
      "Message": None,
  }
  response = requests.post(url, json=payload, headers=headers, timeout=CAI_TIMEOUT)
  response.raise_for_status()
  # ETA 以回應內容的 status 表示結果：200 成功、401 認證失敗、500 其他錯誤
  result = response.json()
  if str(result.get("status")) != "200":
    raise requests.RequestException(f"ETA 回應 {result.get('status')}: {result.get('message')}")
  return response


@app.route("/api/fall_event", methods=["POST"])
def handle_fall_event():
  """接收跌倒事件、推送警告、記錄數據庫"""
  data = request.json or {}
  event_time = data.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
  confidence = float(data.get("confidence", 0.90))
  location = data.get("location", "監控區域")

  logger.info(f"🚨 收到跌倒事件 - 時間: {event_time}, 置信度: {confidence:.2%}, 位置: {location}")

  if not cai_configured() or not USER_ID_TO_PUSH:
    logger.error("❌ c.ai 設定不完整")
    return jsonify({"status": "error", "message": "c.ai 設定不完整"}), 400

  # 第一步：送到 c.ai（由 c.ai 推播卡片到 LINE Bot）
  alert_success = False
  alert_time = None
  try:
    send_fall_event_to_cai(event_time, confidence, location)
    logger.info("✅ 已送出跌倒事件到 c.ai")
    alert_success = True
    alert_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  except requests.RequestException as e:
    logger.error(f"❌ c.ai 送出失敗: {e}")
    alert_success = False

  # 第二步：記錄到數據庫（獨立於 c.ai 送出結果）
  db_success = False
  event_id = None
  try:
    sql = """
      INSERT INTO fall_events
      (user_id, event_time, confidence, location, alert_sent, alert_time, status)
      VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    event_id = MysqlAccess.execute(sql, [
        MONITORED_USER_ID,
        event_time,
        confidence,
        location,
        alert_success,
        alert_time,
        "confirmed" if alert_success else "detected"
    ])
    logger.info(f"✅ 跌倒事件已記錄到數據庫 - 事件 ID: {event_id}")
    db_success = True
  except Exception as e:
    logger.error(f"⚠️  數據庫記錄失敗: {e}（但已送出到 c.ai）", exc_info=True)
    db_success = False

  # 第三步：返回結果
  response = {
      "status": "success" if alert_success else "partial",
      "alert_sent": alert_success,
      "db_recorded": db_success,
      "event_id": event_id,
      "event_time": event_time,
  }

  if alert_success and db_success:
    logger.info(f"✅ 跌倒事件處理完成 - ID: {event_id}")
    return jsonify(response), 200
  elif alert_success or db_success:
    logger.warning(f"⚠️  跌倒事件部分完成 - 警報: {alert_success}, 數據庫: {db_success}")
    return jsonify(response), 200
  else:
    logger.error("❌ 跌倒事件處理失敗")
    return jsonify({"status": "error", "alert_sent": False, "db_recorded": False}), 500


@app.route("/api/fall_events", methods=["GET"])
def get_fall_events():
  """查詢跌倒事件歷史

  查詢參數:
    - limit: 返回的最大記錄數（預設 100）
    - days: 查詢過去 N 天的記錄（預設 7）
  """
  try:
    limit = request.args.get("limit", 100, type=int)
    days = request.args.get("days", 7, type=int)

    sql = """
      SELECT id, user_id, event_time, confidence, location, alert_sent, alert_time, status
      FROM fall_events
      WHERE user_id = %s AND event_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
      ORDER BY event_time DESC
      LIMIT %s
    """

    events = MysqlAccess.query(sql, [MONITORED_USER_ID, days, limit])
    logger.info(f"📊 查詢跌倒事件 - 過去 {days} 天，返回 {len(events)} 條")

    return jsonify({
        "total": len(events),
        "user_id": MONITORED_USER_ID,
        "period_days": days,
        "events": events
    }), 200
  except Exception as e:
    logger.error(f"❌ 查詢跌倒事件失敗: {e}")
    return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
  return jsonify({"status": "ok"}), 200


@app.route("/test_cai", methods=["GET"])
def test_cai():
  """測試 c.ai 送出（c.ai 會推播卡片到 LINE Bot）"""
  print("\n🧪 測試 c.ai 送出...")

  if not cai_configured():
    print("❌ c.ai 設定不完整")
    return jsonify({"error": "c.ai not configured"}), 400

  if not USER_ID_TO_PUSH:
    print("❌ USER_ID 未設定")
    return jsonify({"error": "USER_ID not set"}), 400

  try:
    response = send_fall_event_to_cai(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0.90, "測試區域"
    )
    print(f"✅ c.ai 回應: {response.status_code} {response.text[:200]}")
    return jsonify({"status": "success", "cai_status": response.status_code}), 200
  except Exception as e:
    print(f"❌ 錯誤: {e}")
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
  print("\n🚀 後端已啟動\n")
  app.run(host="0.0.0.0", port=5002, debug=False)
