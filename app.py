from datetime import datetime
import os
import logging
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from linebot import LineBotApi
from linebot.exceptions import LineBotApiError
from linebot.models import FlexSendMessage
from db import MysqlAccess

load_dotenv()

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID_TO_PUSH = os.getenv("LINE_USER_ID")
MONITORED_USER_ID = int(os.getenv("MONITORED_USER_ID", 1))

print("=" * 60)
print("📱 LINE Bot 設定")
print(f"✅ TOKEN: {LINE_CHANNEL_ACCESS_TOKEN[:30]}..." if LINE_CHANNEL_ACCESS_TOKEN else "❌ TOKEN 未設定")
print(f"✅ USER_ID: {USER_ID_TO_PUSH}" if USER_ID_TO_PUSH else "⚠️  USER_ID 未設定")
print(f"✅ 監控用户 ID: {MONITORED_USER_ID}")
print("=" * 60)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None

# 初始化數據庫
try:
    MysqlAccess.init_db()
    logger.info("✅ 數據庫已初始化")
except Exception as e:
    logger.warning(f"⚠️  數據庫初始化失敗: {e}（繼續運行）")


def build_fall_alert_card(timestamp):
  """構建完整的跌倒告警 Flex Message"""
  return {
      "type": "bubble",
      "styles": {
          "header": {"backgroundColor": "#FF3B30"},
          "footer": {"separator": True},
      },
      "header": {
          "type": "box",
          "layout": "vertical",
          "contents": [
              {
                  "type": "text",
                  "text": "🚨 長者跌倒告警 - 緊急...",
                  "weight": "bold",
                  "color": "#FFFFFF",
                  "size": "lg",
              }
          ],
      },
      "body": {
          "type": "box",
          "layout": "vertical",
          "contents": [
              {
                  "type": "text",
                  "text": "⚠️ 偵測到長者跌倒超過 10 秒！",
                  "weight": "bold",
                  "size": "md",
                  "color": "#FF3B30",
                  "wrap": True,
              },
              {
                  "type": "box",
                  "layout": "vertical",
                  "margin": "md",
                  "spacing": "xs",
                  "contents": [
                      {
                          "type": "text",
                          "text": f"📅 時間：{timestamp}",
                          "size": "sm",
                          "color": "#666666",
                      },
                      {
                          "type": "text",
                          "text": "📍 位置：監控區域",
                          "size": "sm",
                          "color": "#666666",
                      },
                      {
                          "type": "text",
                          "text": "🤖 狀態：系統已啟動救援",
                          "size": "sm",
                          "color": "#1DB446",
                          "weight": "bold",
                      },
                  ],
              },
              {"type": "separator", "margin": "md"},
              {
                  "type": "box",
                  "layout": "vertical",
                  "margin": "md",
                  "spacing": "xs",
                  "contents": [
                      {
                          "type": "text",
                          "text": "【救援進程】",
                          "size": "xs",
                          "color": "#888888",
                          "weight": "bold",
                      },
                      {
                          "type": "text",
                          "text": "1️⃣ 系統已確認：跌倒超過 10 秒",
                          "size": "xs",
                          "color": "#333333",
                      },
                      {
                          "type": "text",
                          "text": "2️⃣ 通知家屬：已推播 LINE 告警",
                          "size": "xs",
                          "color": "#FF3B30",
                          "weight": "bold",
                      },
                      {
                          "type": "text",
                          "text": "3️⃣ 立即行動：請確認長者狀態",
                          "size": "xs",
                          "color": "#FF3B30",
                          "weight": "bold",
                      },
                  ],
              },
          ],
      },
      "footer": {
          "type": "box",
          "layout": "vertical",
          "spacing": "sm",
          "contents": [
              {
                  "type": "button",
                  "action": {
                      "type": "message",
                      "label": "✅ 確認平安（解除告警）",
                      "text": "確認長者平安",
                  },
                  "style": "primary",
                  "color": "#1DB446",
              },
          ],
      },
  }


@app.route("/api/fall_event", methods=["POST"])
def handle_fall_event():
  """接收跌倒事件、推送警告、記錄數據庫"""
  data = request.json or {}
  event_time = data.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
  confidence = float(data.get("confidence", 0.90))
  location = data.get("location", "監控區域")

  logger.info(f"🚨 收到跌倒事件 - 時間: {event_time}, 置信度: {confidence:.2%}, 位置: {location}")

  if not line_bot_api or not USER_ID_TO_PUSH:
    logger.error("❌ LINE 設定不完整")
    return jsonify({"status": "error", "message": "LINE 設定不完整"}), 400

  # 第一步：推送 LINE 警報
  alert_success = False
  alert_time = None
  try:
    card = build_fall_alert_card(event_time)
    line_bot_api.push_message(
        USER_ID_TO_PUSH,
        FlexSendMessage(alt_text="🚨 長者跌倒告警", contents=card)
    )
    logger.info("✅ 已推送告警卡片到 LINE")
    alert_success = True
    alert_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  except LineBotApiError as e:
    logger.error(f"❌ LINE 推送失敗: {e}")
    alert_success = False

  # 第二步：記錄到數據庫（獨立於 LINE 推送結果）
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
    logger.error(f"⚠️  數據庫記錄失敗: {e}（但警報已推送）", exc_info=True)
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


@app.route("/test_line", methods=["GET"])
def test_line():
  """測試 LINE 推送"""
  print("\n🧪 測試 LINE 推送...")

  if not line_bot_api:
    print("❌ TOKEN 未設定")
    return jsonify({"error": "TOKEN not set"}), 400

  if not USER_ID_TO_PUSH:
    print("❌ USER_ID 未設定")
    return jsonify({"error": "USER_ID not set"}), 400

  try:
    card = build_fall_alert_card(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    line_bot_api.push_message(
        USER_ID_TO_PUSH,
        FlexSendMessage(alt_text="🧪 測試訊息", contents=card)
    )
    print("✅ 測試卡片已發送")
    return jsonify({"status": "success"}), 200
  except Exception as e:
    print(f"❌ 錯誤: {e}")
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
  print("\n🚀 後端已啟動\n")
  app.run(host="0.0.0.0", port=5002, debug=False)
