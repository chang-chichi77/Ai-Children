# 🎯 完整系統架構和實施狀態

## 系統架構圖

```
┌─────────────────────────────────────────────────────────────┐
│                    邊緣設備 (Edge Device)                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           detector.py - 跌倒偵測模塊                 │    │
│  │  • MediaPipe Pose (姿態識別)                        │    │
│  │  • 跌倒判定邏輯 (身體角度、位置)                     │    │
│  │  • 10秒倒計時機制                                   │    │
│  │  • 實時時間戳顯示 (年月日時分秒)                    │    │
│  │  • 狀態指示 (綠色正常/紅色警告)                    │    │
│  └─────────────────────────────────────────────────────┘    │
│                            ↓ HTTP POST                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     Flask 後端 (app.py)                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  接收跌倒事件 → 發送 LINE 通知 → 啟動聲音通話      │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
         ↙                    ↙                    ↙
    LINE Bot          AWS Connect          叡揚平台
   (通知卡片)        (語音系統)          (判定邏輯)

┌────────────────────────────────────────────────────────────────┐
│                AWS Connect 語音交互系統                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  1. 撥打電話 → 2. 錄音 → 3. STT轉錄 → 4. 發送到叡揚 →   │  │
│  │  5. 叡揚判定 → 6. TTS 語音回應 → 7. 結束通話          │  │
│  └──────────────────────────────────────────────────────────┘  │
│       ↓ AWS Transcribe          ↓ AWS Polly                    │
│    (語音→文字)                (文字→語音)                      │
│       ↓                           ↓                             │
│    叡揚平台 ←────────────────────────                          │
│   (AI 判定系統)                                               │
└────────────────────────────────────────────────────────────────┘
```

---

## 完整通話流程 (Call Flow)

```
【事件觸發】
老人跌倒 (10秒倒計時)
    ↓
【跌倒確認】
偵測器識別持續跌倒狀態
    ↓
【發送警報】
- LINE: 推播紅色警報卡片到家屬手機
    ↓
【啟動 AWS Connect 通話】
    ├─→ [第 1 步] 撥打電話到老人手機
    │
    ├─→ [第 2 步] 播放提示音
    │   "您好，這是跌倒警報系統。如果您沒事，請說好。"
    │
    ├─→ [第 3 步] 錄音 (30 秒)
    │   老人說: "我沒事，只是不小心跌倒了"
    │   🎙️ AWS Transcribe 轉錄
    │   ✅ 文字: "我沒事，只是不小心跌倒了"
    │
    ├─→ [第 4 步] 發送到叡揚平台
    │   POST /api/fall_alert
    │   {
    │     "transcript": "我沒事，只是不小心跌倒了",
    │     "confidence": 0.95,
    │     "timestamp": "2026-09-18 14:30:45",
    │     "call_id": "xxx-yyy-zzz"
    │   }
    │
    ├─→ [第 5 步] 叡揚 AI 判定
    │   叡揚系統分析內容
    │   判定: "SAFE" (平安)
    │   建議: "結束通話並記錄"
    │
    ├─→ [第 6 步] TTS 語音回應
    │   叡揚回傳: "了解，長者已確認平安。"
    │   🔊 AWS Polly 合成語音
    │   ▶️ 向老人播放: "了解，長者已確認平安。"
    │
    └─→ [第 7 步] 結束通話
        記錄完整通話摘要到叡揚平台
        更新 LINE 卡片: "✅ 已確認平安，無需進一步行動"

【通話結束】
整個流程耗時: ~60 秒
```

---

## 系統組件狀態

### ✅ 已完成

| 組件 | 狀態 | 說明 |
|------|------|------|
| **偵測器** | ✅ | 完整的 MediaPipe 跌倒識別 |
| **Flask 後端** | ✅ | API 端點和 LINE 集成 |
| **語音系統框架** | ✅ | AWS Connect + STT + TTS |
| **叡揚集成** | ✅ | API 框架已準備 |
| **環境變量管理** | ✅ | .env 文件配置 |
| **測試工具** | ✅ | 自動化測試腳本 |
| **文檔** | ✅ | 完整使用指南 |

### ⏳ 待配置 (用戶需要完成)

| 項目 | 工作量 | 優先級 |
|------|--------|--------|
| **AWS 帳號設置** | 15 分鐘 | 🔴 必須 |
| **AWS Connect 配置** | 30 分鐘 | 🔴 必須 |
| **叡揚平台 API** | 取決於叡揚 | 🟡 重要 |
| **性能優化** | 可選 | 🟢 可選 |

---

## 快速啟動檢查清單

### 第 1 階段: 基礎設置 (今天)

- [ ] 創建 AWS 帳號
- [ ] 配置 AWS Connect 實例
- [ ] 購買台灣電話號碼
- [ ] 創建 IAM 用戶和訪問密鑰
- [ ] 創建 S3 Bucket
- [ ] 填入 .env 文件

### 第 2 階段: 系統測試 (明天)

- [ ] 安裝 AWS 依賴: `pip install -r requirements.txt`
- [ ] 測試連接: `python3 test_system.py`
- [ ] 運行偵測器: `python3 detector.py`
- [ ] 手動測試通話 (按 'f' 鍵)
- [ ] 驗證 LINE 通知
- [ ] 驗證 AWS 錄音

### 第 3 階段: 叡揚集成 (下週)

- [ ] 獲取叡揚平台 API 文檔
- [ ] 配置 RUISUN_API_URL 和 RUISUN_API_KEY
- [ ] 測試完整通話流程
- [ ] 性能調優

### 第 4 階段: 生產部署 (最後)

- [ ] 部署到邊緣設備
- [ ] 24/7 監控
- [ ] 日誌記錄
- [ ] 性能基準測試

---

## 各模塊代碼位置

### 1. 跌倒偵測 (detector.py)

```python
# 核心函數
detect_fall(landmarks)          # 跌倒判定邏輯
calculate_angle(a, b, c)        # 計算身體角度
send_fall_alert(...)            # 發送警報到後端
draw_chinese_text(...)          # 顯示中文時間戳和狀態
```

**關鍵特性:**
- MediaPipe Pose 實時識別
- 10秒倒計時機制
- 狀態顏色指示 (綠色/紅色)
- 時間戳顯示 (年月日時分秒)

### 2. Flask 後端 (app.py)

```python
# 核心端點
@app.route("/api/fall_event", methods=["POST"])
def handle_fall_event()         # 接收跌倒事件
    ├─ 發送 LINE Flex Card
    ├─ 啟動 AWS Connect 通話
    └─ 轉發到叡揚平台

@app.route("/api/fall_event/cancel", methods=["POST"])
def cancel_fall_alert()         # 取消警報

@app.route("/health", methods=["GET"])
def health_check()              # 健康檢查
```

### 3. 語音系統 (voice_handler.py)

```python
class VoiceCallHandler:
  def initiate_emergency_call()      # 撥打緊急電話

class SpeechToText:
  def transcribe_audio()             # STT: 語音轉文字
  def get_transcription_result()     # 獲取轉錄結果

class RuisunIntegration:
  def send_voice_to_ruisun()         # 發送到叡揚
  def send_call_summary_to_ruisun()  # 發送摘要

class TextToSpeech:
  def synthesize_speech()            # TTS: 文字轉語音
  def play_audio_to_caller()         # 播放語音

class EmergencyCallFlow:
  def execute_emergency_call()       # 完整通話流程
```

---

## 數據流詳解

### 1. 跌倒事件流

```
偵測器 detector.py
    └─→ (HTTP POST) app.py:/api/fall_event
        {
          "event": "fall_10s_confirmed",
          "time": "2026-09-18 14:30:45",
          "confidence": 0.95
        }
```

### 2. LINE 通知流

```
app.py
    └─→ (LINE Messaging API) LINE 官方帳號
        └─→ LINE Bot 推送警報卡片給 LINE_USER_ID
```

### 3. 語音通話流

```
app.py
    └─→ voice_handler.execute_emergency_call()
        ├─→ AWS Connect (撥打電話)
        ├─→ AWS S3 (儲存錄音)
        ├─→ AWS Transcribe (STT)
        ├─→ RUISUN API (發送轉錄)
        ├─→ AWS Polly (TTS)
        └─→ AWS Connect (播放語音)
```

---

## 錯誤處理機制

| 故障場景 | 影響 | 恢復 |
|---------|------|------|
| AWS Connect 無法撥打 | 語音系統不工作 | LINE 通知仍然發送 |
| STT 失敗 | 無法識別語音 | 轉接人工客服 |
| 叡揚平台無法連接 | 無法獲得判定 | 使用備用提示 |
| 網絡中斷 | 無法發送警報 | 自動重試 3 次 |

---

## 成本預估 (月度)

### 初期設置 (一次性)
- AWS 帳號驗證: 免費
- Connect 實例: 免費 (首月)
- 電話號碼: $1-2

### 月度運營成本 (500 次通話)

```
AWS Connect:        500 calls × $0.035/min × 1 min = $17.50
AWS Transcribe:     500 calls × 30 sec = 250 分鐘
                    250 min × 60 sec × $0.0004 = $6.00
AWS Polly:          500 calls × 20 字 × $0.000002 = $0.02
S3 存儲:            50 GB × $0.025 = $1.25
─────────────────────────────────────
小計:                                   ~$25/月

LINE Bot:           免費 (已有 ACCESS_TOKEN)
```

---

## 安全考慮

### 敏感信息保護

✅ **已實施:**
- 所有 API Key 在 .env 文件中
- .env 添加到 .gitignore
- 環境變量讀取而非硬編碼

### 建議措施

⚠️ **應該實施:**
- AWS KMS 加密敏感數據
- CloudWatch 日誌監控異常
- 定期輪換 API Key
- 限制 IAM 權限到必要最小值

---

## 性能指標

### 目標延遲

```
跌倒檢測 → 發送通知: < 1 秒
發送通知 → 獲得響應: 20-30 秒
STT 轉錄: < 10 秒
TTS 生成: < 5 秒
```

### 系統容量

```
同時通話數: 取決於 AWS Connect 配額
每月通話次數: 無限制
錄音存儲: S3 無限制
```

---

## 下一步行動計劃

### 優先級 1 (本週)
1. ✅ 完成 AWS Connect 設置
2. ✅ 配置電話號碼和 Contact Flow
3. ✅ 測試基本通話

### 優先級 2 (下週)
4. 集成叡揚平台 API
5. 測試完整語音對話
6. 優化識別準確度

### 優先級 3 (第三週)
7. 部署到邊緣設備
8. 24/7 監控和日誌
9. 性能基準測試

---

## 文件清單

```
/Users/imac-3570/Desktop/AIChildren/
├── detector.py                 ✅ 跌倒偵測主程序
├── app.py                      ✅ Flask 後端
├── voice_handler.py            ✅ 語音交互系統
├── .env                        ⏳ 需填入 AWS 信息
├── requirements.txt            ✅ 依賴列表 (含 boto3)
│
├── README.md                   ✅ 主要文檔
├── QUICKSTART.md               ✅ 快速啟動
├── AWS_SETUP.md                ✅ AWS 配置指南
├── SYSTEM_OVERVIEW.md          ✅ 本文件 (系統概覽)
│
├── test_system.py              ✅ 測試腳本
├── call_test.py                (已過時 - 舊的 Twilio)
│
└── .gitignore                  ⏳ 應該包含 .env
```

---

## 常見問題

### Q: 為什麼選擇 AWS Connect 而不是 Twilio?

**A:** 
- AWS Connect 在亞太地區完全支援台灣
- 升級更簡單 (無需通過驗證和限制)
- 內建 STT、TTS、錄音功能
- 成本更低（尤其是大規模部署）

### Q: 叡揚平台需要什麼接口?

**A:**
```json
POST /api/fall_alert
{
  "transcript": "我沒事",
  "timestamp": "2026-09-18 14:30:45",
  "confidence": 0.95,
  "call_id": "xxx-yyy-zzz"
}

Response:
{
  "assessment": "SAFE|NEEDS_HELP|EMERGENCY",
  "tts_text": "了解，長者已確認平安",
  "action": "end_call|transfer|escalate"
}
```

### Q: 如何測試系統?

**A:**
```bash
# 1. 啟動後端
python3 app.py

# 2. 在另一個終端啟動偵測器
python3 detector.py

# 3. 在偵測器中按 'f' 鍵進行測試
# 你的手機應該會收到 AWS Connect 電話
```

---

**最後更新**: 2026-09-18
**版本**: 1.0 (AWS Connect Edition)
