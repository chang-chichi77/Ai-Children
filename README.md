# 🚨 阿公阿嬤的AI孫 - 跌倒偵測系統

完整的老人跌倒偵測和緊急通知系統，使用MediaPipe姿態識別 + OpenCV + Flask + LINE Bot + Twilio。

## 📋 系統架構

```
邊緣設備 (detector.py)
    ↓ [MediaPipe 姿態偵測]
    ↓ [跌倒判定邏輯]
    ↓ [10秒倒計時]
    ↓ HTTP POST
Flask 後端 (app.py:5002)
    ↓ [LINE 推播]
    ↓ [Twilio 電話外撥]
    ↓ [叡揚平台轉發]
LINE Bot → 家屬
Twilio → 緊急電話
叡揚平台 → 其他服務
```

## 🚀 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 配置環境變量

編輯 `.env` 文件，填入：
- `LINE_CHANNEL_ACCESS_TOKEN`: LINE Bot 的頻道存取權杖
- `LINE_USER_ID`: 接收通知的LINE用戶ID
- `TWILIO_ACCOUNT_SID`: Twilio 帳號SID
- `TWILIO_AUTH_TOKEN`: Twilio 認證令牌
- `TWILIO_PHONE_NUMBER`: Twilio 虛擬號碼
- `EMERGENCY_PHONE`: 緊急聯絡電話

### 3. 啟動 Flask 後端

```bash
python app.py
# 服務運行在 http://127.0.0.1:5002
```

### 4. 啟動跌倒偵測

```bash
python detector.py
```

## ✨ 功能說明

### 偵測器 (detector.py)

**實時姿態偵測**
- 使用 MediaPipe Pose 進行身體姿態識別
- 每幀處理，實時輸出

**跌倒判定邏輯**
- 肩膀傾斜度 > 50° 
- 頭部位置在身體下方
- 腿部伸直角度 > 150°

**狀態機制**
- 🟢 **正常監控**: 顯示綠色狀態
- 🔴 **跌倒警告**: 檢測到跌倒，開始10秒倒計時
- 🚨 **確認跌倒**: 保持跌倒姿勢10秒後自動觸發警報

**快捷鍵**
- `f`: 手動測試警報系統
- `q`: 退出程式

### 後端 (app.py)

**API 端點**

#### 1. 接收跌倒事件
```bash
POST /api/fall_event
Content-Type: application/json

{
  "event": "fall_10s_confirmed",
  "time": "2026-09-18 14:30:45",
  "confidence": 0.95
}
```

**響應**:
```json
{
  "status": "success",
  "message": "Alert processed and notifications sent",
  "event_type": "fall_10s_confirmed",
  "timestamp": "2026-09-18 14:30:45"
}
```

#### 2. 取消警報
```bash
POST /api/fall_event/cancel
```

#### 3. 健康檢查
```bash
GET /health
```

**自動執行流程**
1. 接收跌倒事件
2. 立即發送 LINE Flex Card 通知
3. 觸發 Twilio 電話外撥
4. 轉發至叡揚平台（如已配置）

## ⚠️ 電話撥打問題 - Twilio 付費方案

### 現狀
- ✅ **Twilio 免費帳號**: 只能撥打已驗證的電話號碼
- ❌ 無法撥打真實用戶電話
- ⚠️ 您的帳號目前無法升級方案

### 解決方案

#### 方案 A: 升級 Twilio 付費方案（推薦）
1. 登入 [Twilio 控制台](https://console.twilio.com)
2. 進入 **Account Settings** → **Upgrade Account**
3. 填入信用卡信息完成升級
4. 升級後可撥打真實電話

#### 方案 B: 使用 Twilio 測試模式
1. 在免費帳號中，先驗證接收電話號碼
2. 在撥號前執行驗證流程

#### 方案 C: 整合其他服務提商
可以使用替代服務：
- **Google Cloud Dialogflow**: 語音通話
- **AWS Connect**: 企業級通話
- **Nexmo/Vonage**: 語音API

## 🔗 叡揚平台整合

### 配置步驟

1. **在 .env 中填入叡揚平台信息**
```env
RUISUN_API_URL=https://your-ruisun-platform-url/api/fall_alert
RUISUN_API_KEY=your_ruisun_api_key
```

2. **系統會自動轉發跌倒事件**

跌倒事件會同時發送到：
- ✅ LINE Bot (立即推播)
- ✅ 本地 Flask API
- ✅ Twilio (電話外撥)
- ✅ 叡揚平台 (如已配置)

### 預期叡揚平台響應格式

```json
{
  "event_type": "fall_10s_confirmed",
  "timestamp": "2026-09-18 14:30:45",
  "confidence": 0.95,
  "user_id": "LINE_USER_ID",
  "phone": "+886909949558",
  "status": "alert_sent"
}
```

## 🧪 測試步驟

### 1. 測試後端連接

```bash
# 啟動 Flask (在另一個終端)
python app.py

# 測試 API
curl -X POST http://localhost:5002/api/fall_event \
  -H "Content-Type: application/json" \
  -d '{
    "event": "fall_10s_confirmed",
    "time": "2026-09-18 14:30:45",
    "confidence": 0.95
  }'
```

### 2. 測試偵測器

```bash
python detector.py

# 在偵測器運行時按 'f' 鍵進行手動測試
# 應該看到:
# - LINE 推播收到告警
# - 後台嘗試撥打電話（需付費方案）
# - 日誌顯示所有操作狀態
```

### 3. 測試叡揚平台連接

確保在 `.env` 中配置了 `RUISUN_API_URL` 和 `RUISUN_API_KEY`，然後運行測試。

## 📊 實時監控指標

偵測器會顯示：
- **時間戳**: 年月日時分秒
- **狀態**: 正常(綠色) / 警告(紅色)
- **倒計時**: 跌倒持續時間
- **信心度**: 姿態識別準確度

## 🔒 安全建議

- ✅ 所有敏感信息已移至 `.env` 文件
- ✅ 使用環境變量讀取配置
- ⚠️ 不要提交 `.env` 文件到 Git
- ⚠️ 定期更換 API Key 和 Access Token

### .gitignore

```
.env
.env.local
__pycache__/
*.pyc
.DS_Store
```

## 📞 支援和故障排除

### 偵測不到跌倒？
1. 確保光線充足
2. 調整攝像頭角度和高度
3. 在 `detect_fall()` 中調整閾值

### LINE 推播沒收到？
1. 檢查 `LINE_CHANNEL_ACCESS_TOKEN` 是否正確
2. 檢查 `LINE_USER_ID` 是否正確
3. 檢查 Flask 是否正在運行

### 電話無法撥出？
1. ✅ **必須升級 Twilio 付費方案** (見上文)
2. 檢查 Twilio 帳號是否已驗證
3. 檢查 `EMERGENCY_PHONE` 格式（需含國碼）

### 叡揚平台無法連接？
1. 確認 `RUISUN_API_URL` 是否正確
2. 檢查 API Key 是否有效
3. 查看 Flask 日誌輸出的錯誤訊息

## 📝 日誌輸出範例

```
🚀 MediaPipe 跌倒偵測系統已啟動...
💡 提示：按下 "q" 鍵退出，"f" 鍵手動測試

[偵測正常]
✅ 正常監控中 (2026-09-18 14:30:45)

[偵測到跌倒]
⚠️ 【2026-09-18 14:30:50】偵測到潛在跌倒！開始倒計時...
[顯示: 倒計時 9.5秒]

[確認跌倒]
🚨 【2026-09-18 14:31:00】確認跌倒！已保持跌倒姿勢 10 秒
📩 收到跌倒事件訊號: fall_10s_confirmed (信心度: 0.95)
✅ LINE 救援三階段告警卡片發送成功！
📞 準備發起 Twilio 電話外撥...
✅ 已轉發至叡揚平台
```

## 🎯 下一步

1. **升級 Twilio 付費方案** - 啟用電話撥打功能
2. **配置叡揚平台** - 填入 API URL 和 Key
3. **測試完整流程** - 模擬跌倒情景
4. **部署邊緣設備** - 在實際環境中運行

## 📄 相關文檔

- [LINE Messaging API](https://developers.line.biz/zh-hant/reference/messaging-api/)
- [Twilio Voice API](https://www.twilio.com/en-us/voice)
- [MediaPipe Pose](https://google.github.io/mediapipe/solutions/pose.html)
- [OpenCV](https://opencv.org/)

---

**最後更新**: 2026-09-18
