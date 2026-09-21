from datetime import datetime
import os
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from linebot import LineBotApi
from linebot.models import FlexSendMessage

load_dotenv()

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID_TO_PUSH = os.getenv("LINE_USER_ID")

print("=" * 60)
print("📱 LINE Bot 設定")
print(f"✅ TOKEN: {LINE_CHANNEL_ACCESS_TOKEN[:30]}..." if LINE_CHANNEL_ACCESS_TOKEN else "❌ TOKEN 未設定")
print(f"✅ USER_ID: {USER_ID_TO_PUSH}" if USER_ID_TO_PUSH else "⚠️  USER_ID 未設定")
print("=" * 60)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None


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
  """接收跌倒事件並推送警告"""
  data = request.json or {}
  event_time = data.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

  print(f"\n🚨 【{event_time}】收到跌倒事件")

  if not line_bot_api or not USER_ID_TO_PUSH:
    print("❌ LINE 設定不完整")
    return jsonify({"status": "error"}), 400

  try:
    card = build_fall_alert_card(event_time)
    line_bot_api.push_message(
        USER_ID_TO_PUSH,
        FlexSendMessage(alt_text="🚨 長者跌倒告警", contents=card)
    )
    print(f"✅ 已推送告警卡片到 LINE")
    return jsonify({"status": "success"}), 200
  except Exception as e:
    print(f"❌ 推送失敗: {e}")
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
