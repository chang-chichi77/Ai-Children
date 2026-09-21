# 獨居老人跌倒偵測系統重設計文檔

**日期：** 2026-09-18  
**狀態：** 架構設計已批准  
**目標完成日期：** Demo 完成

---

## 1. 背景與需求

### 問題
- 原方案嘗試透過 Python 撥打電話通知，技術實現困難且不可靠
- 需要一個可行的、Demo 友善的方案，能實時通知監護人和醫護人員

### 解決方案方向
改為 **影像傳輸 + LINE Bot 通知** 的異步處理架構，核心優勢：
- 利用既有 LINE Bot 作為通知通道（實現快速、演示友善）
- 異步處理確保攝影機檢測不中斷
- 完整事件記錄可查，符合醫療紀錄需求

### 設計場景
- **監控對象：** 獨居老人（客廳攝影機）
- **檢測條件：** 持續 10 秒跌倒狀態
- **通知對象：** 医護人員（透過 LINE 群組）
- **數據保留期：** 1 個月
- **醫護決策：** 在 LINE 上人工判斷是否派救護車

---

## 2. 整體架構

```
┌──────────────────────┐
│  攝影機 (客廳)        │
│  MediaPipe+OpenCV    │ ← 持續檢測，10秒跌倒判定
└──────────┬───────────┘
           │
           ├─ 檢測到跌倒持續 ≥ 10 秒
           │
           ↓
┌─────────────────────────────────────┐
│  Flask 後端 API                     │
│  ├─ POST /api/detect                │
│  ├─ GET /api/elderly/{id}/events    │
│  ├─ POST /api/events/{id}/confirm   │
│  └─ 定時清理過期資料                │
└──────────┬────────────────────────┘
           │
    ┌──────┴──────┐
    │ 寫入         │ 觸發
    ↓             ↓
┌─────────┐  ┌──────────────────┐
│ MySQL   │  │ Celery 任務隊列  │
│ 資料庫   │  │ (或 RQ)          │
│ 10幀    │  │ 生成GIF          │
│ + 事件   │  │ + 傳LINE         │
└────┬────┘  │ + 更新狀態      │
     │       └────────┬────────┘
     │                │
     └────────────────┼──────────────┐
                      │              │
                      ↓              ↓
             ┌──────────────┐  ┌──────────────┐
             │  文件存儲     │  │  LINE Bot    │
             │ (GIF + 截圖) │  │  (向醫護)    │
             └──────────────┘  └──────────────┘
```

---

## 3. 資料庫設計

### 表 3.1：elderly_info (老人基本資訊)

| 欄位名 | 型別 | 說明 |
|--------|------|------|
| elderly_id | INT PRIMARY KEY | 老人唯一ID |
| name | VARCHAR(100) | 姓名 |
| address | TEXT | 住址 |
| birth_date | DATE | 出生年月日 |
| blood_type | VARCHAR(10) | 血型 |
| family_contact_name | VARCHAR(100) | 家屬名字 |
| family_phone | VARCHAR(20) | 家屬聯絡電話 |
| line_notify_id | VARCHAR(255) | LINE 接收群組/帳號ID |
| created_at | TIMESTAMP | 建檔時間 |
| updated_at | TIMESTAMP | 更新時間 |

### 表 3.2：fall_events (跌倒事件記錄)

| 欄位名 | 型別 | 說明 |
|--------|------|------|
| event_id | VARCHAR(50) PRIMARY KEY | 事件ID (evt_YYYYMMDD_NNN) |
| elderly_id | INT FK | 關聯老人 |
| fall_start_time | TIMESTAMP | 跌倒開始時間 |
| fall_end_time | TIMESTAMP NULL | 跌倒結束時間（可自己站起來） |
| duration_seconds | INT | 持續秒數（≥10觸發警報） |
| event_status | ENUM | 檢測中/待確認/已派救護車/誤判/其他 |
| line_message_id | VARCHAR(255) NULL | LINE訊息ID（用於追蹤） |
| screenshot_dir | VARCHAR(255) | 10張截圖存放目錄 |
| gif_path | VARCHAR(255) NULL | 生成GIF的路徑 |
| created_at | TIMESTAMP | 事件建立時間 |
| expire_at | TIMESTAMP | 1個月後到期（用於自動清理） |
| INDEX (elderly_id, created_at) | - | 查詢加速 |

### 表 3.3：fall_screenshots (截圖記錄，可選但建議)

| 欄位名 | 型別 | 說明 |
|--------|------|------|
| screenshot_id | INT PRIMARY KEY | 截圖ID |
| event_id | VARCHAR(50) FK | 關聯事件 |
| screenshot_num | INT (1-10) | 序號 |
| file_path | VARCHAR(255) | 檔案路徑 |
| timestamp | TIMESTAMP | 截圖時間戳 |

---

## 4. API 設計

### 4.1 POST /api/detect
**攝影機呼叫此端點，上傳跌倒檢測結果**

**請求：**
```json
{
  "elderly_id": 1,
  "screenshots": [
    "base64_image_1",
    "base64_image_2",
    "...",
    "base64_image_10"
  ],
  "timestamps": [
    1726700000,
    1726700001,
    1726700002,
    "...",
    1726700009
  ]
}
```

**回應 (200 OK)：**
```json
{
  "success": true,
  "event_id": "evt_20260918_001",
  "message": "跌倒事件已記錄，正在生成警報"
}
```

**流程：**
1. 驗證 elderly_id 存在
2. 驗證有 10 張截圖
3. 儲存到磁碟 (`/app/storage/elderly_{id}/YYYY-MM-DD_HH-MM-SS/`)
4. 寫入資料庫 (status = '檢測中')
5. 推送 Celery 任務到隊列
6. 立即回應給攝影機（不阻塞）

---

### 4.2 GET /api/elderly/{elderly_id}/events
**查詢某老人的事件歷史**

**查詢參數：**
- `limit`: 返回筆數，預設 10
- `status`: 篩選狀態 (all/檢測中/待確認/已派救護車/誤判)
- `date_from`: 開始日期 (YYYY-MM-DD)
- `date_to`: 結束日期 (YYYY-MM-DD)

**範例：** `GET /api/elderly/1/events?limit=20&status=已派救護車`

**回應 (200 OK)：**
```json
{
  "success": true,
  "elderly_id": 1,
  "name": "王老奶奶",
  "events": [
    {
      "event_id": "evt_20260918_001",
      "fall_start_time": "2026-09-18 14:30:45",
      "fall_end_time": "2026-09-18 14:30:55",
      "duration_seconds": 10,
      "event_status": "已派救護車",
      "line_message_id": "msg_xyz123",
      "gif_url": "/videos/evt_20260918_001.gif",
      "created_at": "2026-09-18 14:30:50"
    }
  ]
}
```

---

### 4.3 POST /api/events/{event_id}/confirm
**醫護人員在 LINE 上點擊按鈕後，後端更新事件狀態**

**請求：**
```json
{
  "action": "已派救護車",
  "notes": "病人已送往醫院" 
}
```

**可用的 action：**
- `已派救護車`
- `誤判`
- `暫時觀察`
- 其他自定義狀態

**回應 (200 OK)：**
```json
{
  "success": true,
  "event_id": "evt_20260918_001",
  "updated_status": "已派救護車"
}
```

---

## 5. 後台任務流程（Celery 或 RQ）

### 5.1 任務觸發時機
Flask `/api/detect` 端點接收到跌倒信號 → 推送任務到隊列

### 5.2 任務執行流程

**步驟 1：讀取截圖**
```python
# 從磁碟讀取 10 張 JPEG 截圖
screenshots = [
  imread(f"/app/storage/elderly_1/2026-09-18_14-30-45/frame_01.jpg"),
  ...
  imread(f"/app/storage/elderly_1/2026-09-18_14-30-45/frame_10.jpg")
]
```

**步驟 2：生成 GIF**
```python
# 用 OpenCV + imageio 將 10 幀生成 GIF（1秒1幀，共10秒）
imageio.mimsave(
  "/app/storage/elderly_1/2026-09-18_14-30-45.gif",
  screenshots,
  duration=1.0,  # 每幀 1 秒
  loop=1         # 不循環
)
```

**步驟 3：組裝 LINE 訊息**
```python
elderly_info = db.query(ElderlYInfo).get(elderly_id=1)

message = f"""
⚠️ **跌倒警報**

姓名：{elderly_info.name}
住址：{elderly_info.address}
生日：{elderly_info.birth_date}
血型：{elderly_info.blood_type}

家屬：{elderly_info.family_contact_name}
聯絡：{elderly_info.family_phone}

🎬 檢測影片已附件
⏰ 檢測時間：2026-09-18 14:30:45
⏱️  持續時間：10 秒

請確認是否需要派救護車
"""
```

**步驟 4：上傳 GIF 到 LINE Bot**
```python
line_bot_api.push_message(
  to=elderly_info.line_notify_id,
  messages=[
    TextMessage(text=message),
    ImageMessage(
      original_content_url="https://your-domain.com/videos/evt_20260918_001.gif",
      preview_image_url="https://your-domain.com/videos/evt_20260918_001_thumb.jpg"
    )
  ]
)
```

**步驟 5：更新資料庫**
```python
db.fall_events.update(
  event_id="evt_20260918_001",
  status="待確認",
  gif_path="/app/storage/elderly_1/2026-09-18_14-30-45.gif",
  line_message_id="msg_from_line_api"
)
```

### 5.3 失敗重試機制
- 如果 LINE API 失敗，Celery 自動重試 3 次（指數退避）
- 如果 GIF 生成失敗，記錄錯誤並發送告警訊息給醫護

---

## 6. 文件存儲結構

```
/app/storage/
├─ elderly_1/
│  ├─ 2026-09-18_14-30-45/
│  │  ├─ frame_01.jpg
│  │  ├─ frame_02.jpg
│  │  ├─ ...
│  │  └─ frame_10.jpg
│  ├─ 2026-09-18_14-30-45.gif
│  ├─ 2026-09-19_10-15-22/
│  └─ ...
├─ elderly_2/
│  ├─ 2026-09-18_09-45-30/
│  └─ ...
└─ ...
```

**清理政策：** 
- Celery Beat 每天午夜 00:00 執行清理任務
- 刪除 expire_at 已過期的事件和相應檔案

---

## 7. 部署與環境

### 技術棧
- **後端：** Python 3.8+ + Flask
- **任務隊列：** Celery + Redis（或 RQ + Redis）
- **資料庫：** MySQL 8.0+
- **檔案存儲：** 本地磁碟（Demo）或 S3/雲端存儲（正式環境）
- **通知：** LINE Bot API

### 配置需求
```
.env:
DATABASE_URL=mysql+pymysql://user:password@localhost/elderly_db
REDIS_URL=redis://localhost:6379/0
LINE_BOT_CHANNEL_ID=your_channel_id
LINE_BOT_CHANNEL_SECRET=your_channel_secret
STORAGE_PATH=/app/storage
```

---

## 8. 測試策略

### 8.1 單元測試
- `test_detection_logic.py` — 跌倒檢測邏輯（MediaPipe）
- `test_gif_generation.py` — GIF 生成函數
- `test_api_validation.py` — API 輸入驗證

### 8.2 集成測試
- Mock LINE Bot API，測試完整流程
- 測試資料庫插入、查詢、更新
- 測試後台任務隊列執行
- 測試過期資料自動清理

### 8.3 Demo 測試流程
1. **準備：** 資料庫預先插入一個老人記錄 (elderly_id=1)
2. **模擬跌倒：** 執行 10 秒跌倒動作，系統檢測並上傳 10 張截圖
3. **驗證 LINE：** 在 LINE 群組收到警報訊息 + GIF
4. **檢查資料庫：** 查詢 fall_events 表確認事件已記錄
5. **查詢歷史：** 呼叫 GET /api/elderly/1/events 驗證可查

---

## 9. 實施時程

| 階段 | 任務 | 預計時間 |
|------|------|--------|
| **Phase 1** | 資料庫設計 + 初始化 SQL | 1 小時 |
| **Phase 2** | Flask API 三個端點實裝 | 2 小時 |
| **Phase 3** | Celery 任務隊列 + GIF 生成 | 2 小時 |
| **Phase 4** | LINE Bot 整合 | 1.5 小時 |
| **Phase 5** | 單元測試 + 集成測試 | 2 小時 |
| **Phase 6** | Demo 測試 + 影片錄製 | 1.5 小時 |
| **總計** | - | **10 小時** |

---

## 10. 風險與假設

### 假設
- LINE Bot 已經可用，有有效的 Channel ID 和 Secret
- 攝影機可以穩定連接到後端 API
- 醫護人員有 LINE 客戶端接收訊息

### 潛在風險
| 風險 | 緩解方案 |
|------|--------|
| GIF 文件太大，LINE 傳輸失敗 | 壓縮 GIF；如果失敗，傳送截圖列表代替 |
| 資料庫連接超時 | 設置連接池，配置重試邏輯 |
| Celery 任務堆積 | 監控隊列長度，必要時增加 Worker |
| 過期資料清理失敗 | 日誌記錄，告警通知管理者手動清理 |

---

## 11. 未來擴展

- **Phase 2：** 醫護人員確認機制（已預留 API `/api/events/{id}/confirm`）
- **Phase 3：** 多攝影機支援（每個老人多個房間）
- **Phase 4：** AI 誤判調整（改進跌倒檢測準確度）
- **Phase 5：** 完整醫療記錄系統（與醫院 HIS 整合）

---

**文檔版本：** 1.0  
**最後更新：** 2026-09-18  
**審核者：** (待批准)
