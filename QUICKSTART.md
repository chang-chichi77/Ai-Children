# 🚀 快速啟動指南

## 1️⃣ 前置準備

### 檢查系統依賴

```bash
cd /Users/imac-3570/Desktop/AIChildren

# 驗證 Python 3.8+
python3 --version

# 驗證依賴已安裝
python3 -m pip list | grep -E "opencv|mediapipe|flask|twilio"
```

### 環境變量已配置 ✅

```bash
# 檢查 .env 文件
cat .env
```

**需要填入的信息:**
- ✅ LINE 相關信息 (已配置)
- ✅ Twilio 相關信息 (已配置)
- ⚠️ 叡揚平台信息 (選擇性)

---

## 2️⃣ 啟動系統（分3個終端）

### 終端 1: 啟動 Flask 後端

```bash
cd /Users/imac-3570/Desktop/AIChildren
python3 app.py
```

**預期輸出:**
```
 * Serving Flask app 'app'
 * Running on http://127.0.0.1:5002
```

### 終端 2: 啟動跌倒偵測

```bash
cd /Users/imac-3570/Desktop/AIChildren
python3 detector.py
```

**預期輸出:**
```
🚀 MediaPipe 跌倒偵測系統已啟動...
💡 提示：按下 "q" 鍵退出，"f" 鍵手動測試
✅ 正常監控中 (2026-09-18 14:30:45)
```

### 終端 3: 運行測試（可選）

```bash
cd /Users/imac-3570/Desktop/AIChildren
python3 test_system.py
```

---

## 3️⃣ 測試流程

### A. 手動測試警報系統

1. **偵測器運行中**, 按鍵盤 **`f` 鍵**
2. **預期結果:**
   - 終端顯示: `【時間】手動觸發測試！`
   - LINE Bot 收到緊急告警通知
   - Flask 後台嘗試撥打電話
   - 日誌顯示所有操作狀態

### B. 測試實際跌倒偵測

1. 在攝像頭前**模擬跌倒動作** (身體平躺)
2. 系統會:
   - 🟢 顯示 **綠色** 正常監控
   - 🔴 顯示 **紅色** 警告 (檢測到跌倒)
   - ⏱️ 開始 **10秒倒計時**
3. **10秒後** 如仍保持跌倒:
   - 🚨 自動觸發警報
   - 發送 LINE 通知
   - 嘗試撥打電話

---

## 4️⃣ 解決電話撥打問題

### ⚠️ 當前狀況

```
❌ Twilio 免費帳號無法撥打真實電話
   只能撥打已驗證的測試號碼
```

### ✅ 升級步驟 (5分鐘完成)

1. 打開瀏覽器進入 [Twilio 控制台](https://console.twilio.com)
2. 登入你的帳號
3. 左側菜單 → **Account** → **Account Settings**
4. 點擊右上角 **Upgrade Account** 按鈕
5. 填入信用卡信息
6. 確認升級

✅ **升級完成後可立即撥打真實電話**

### 驗證升級成功

```bash
python3 call_test.py
# 應該收到實際的電話呼叫
```

---

## 5️⃣ 配置叡揚平台 (可選)

### 步驟 1: 獲取叡揚平台 API 信息

聯繫叡揚技術支持獲取:
- API 端點 URL
- API Key 或 Access Token

### 步驟 2: 更新 .env 文件

編輯 `.env`:

```env
# 叡揚平台設定
RUISUN_API_URL=https://your-ruisun-api-url/fall_alert
RUISUN_API_KEY=your_api_key_here
```

### 步驟 3: 驗證連接

系統會自動轉發警報到叡揚平台:

```
✅ 已轉發至叡揚平台 (200)
```

---

## 6️⃣ 實際部署

### 在邊緣設備上運行

```bash
# 長期運行建議用 tmux 或 screen

# 方式 1: 使用 tmux
tmux new-session -d -s "fall_detection" "python3 /path/to/detector.py"
tmux new-window -t "fall_detection" "python3 /path/to/app.py"

# 方式 2: 使用 systemd service (Linux)
# 創建 /etc/systemd/system/fall-detection.service
```

### 保持進程運行

```bash
# 檢查進程狀態
ps aux | grep detector
ps aux | grep app.py

# 查看日誌
tail -f detector_output.log
tail -f app_output.log
```

---

## 7️⃣ 常見問題

### Q1: 媒體庫找不到怎麼辦？

```bash
# 重新安裝依賴
pip3 install --upgrade -r requirements.txt

# 如果還有問題，逐個安裝
pip3 install opencv-python mediapipe flask line-bot-sdk twilio
```

### Q2: 攝像頭無法打開？

```python
# 測試攝像頭
python3 -c "import cv2; cap = cv2.VideoCapture(0); print(cap.isOpened())"
# 應輸出 True

# 如果是 False，嘗試
import cv2
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FPS, 30)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
```

### Q3: LINE 通知未收到？

1. 檢查 `LINE_USER_ID` 是否正確
   ```bash
   grep LINE_USER_ID .env
   ```

2. 檢查 LINE Bot 是否已啟用
   - 進入 [LINE Developers](https://developers.line.biz/)
   - 檢查 Bot 狀態是否為「啟用」

3. 檢查消息推送設置
   ```bash
   # 測試 API
   curl -X POST http://localhost:5002/api/fall_event \
     -H "Content-Type: application/json" \
     -d '{"event":"fall_10s_confirmed","time":"2026-09-18 14:30:45","confidence":0.95}'
   ```

### Q4: Twilio 電話還是撥不出去？

✅ **必須升級付費方案** (見 4️⃣ 部分)

免費帳號限制:
- ❌ 無法撥打真實用戶
- ✅ 只能撥打已驗證的測試號碼

---

## 8️⃣ 監控和維護

### 日誌檢查

```bash
# 實時查看偵測器日誌
tail -f ~/detector.log

# 查看 Flask 錯誤
grep -i "error" ~/flask.log

# 查看 Twilio 嘗試
grep -i "twilio" ~/app.log
```

### 性能優化

如果 CPU 使用率過高:

```python
# 在 detector.py 中調整
pose = mp_pose.Pose(
  static_image_mode=False,
  model_complexity=0,  # 降低複雜度 (0=lite, 1=full, 2=heavy)
  smooth_landmarks=True,
)

# 降低幀率
cap.set(cv2.CAP_PROP_FPS, 15)  # 15 FPS 而不是 30
```

### 定期檢查

每週檢查:
- ✅ Twilio 餘額
- ✅ LINE Bot 消息限制
- ✅ 系統日誌有無錯誤
- ✅ 攝像頭是否正常

---

## 9️⃣ 故障恢復

### 系統崩潰恢復

```bash
# 殺死所有 Python 進程
pkill -f "python3 detector.py"
pkill -f "python3 app.py"

# 重啟系統
python3 detector.py &
python3 app.py &
```

### 清空日誌

```bash
# 清空老日誌
> ~/detector.log
> ~/app.log
```

---

## 🔟 下一步

1. ✅ **啟動系統**: 按照上述步驟啟動
2. ✅ **升級 Twilio**: 實現真實電話撥打
3. ✅ **配置叡揚**: 集成叡揚平台
4. ✅ **部署邊緣設備**: 在真實環境中運行
5. ✅ **監控告警**: 設置24/7監控

---

**需要幫助？** 查看 `README.md` 獲取更多信息

**最後更新**: 2026-09-18
