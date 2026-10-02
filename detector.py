#!/usr/bin/env python3
import argparse
import math
import os
import threading
import time
from collections import deque
import cv2
import numpy as np
from datetime import datetime
import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions
import mediapipe as mp

from vllm_confirm import confirm_fall

load_dotenv()

VLLM_BASE_URL = os.environ.get("FALL_DETECT_BASE_URL", "http://10.0.0.206:8010/v1")
VLLM_MODEL = os.environ.get("FALL_DETECT_MODEL", "gemma-4-26b")
VLLM_COOLDOWN_SECONDS = 5  # vLLM 否決跌倒後的冷卻時間,避免持續阻塞主迴圈重複呼叫

FLASK_API_URL = 'http://127.0.0.1:5002/api/fall_event'
POSE_MODEL_PATH = os.path.join(os.path.dirname(__file__), 'pose_landmarker_lite.task')
OBJECT_MODEL_PATH = os.path.join(os.path.dirname(__file__), 'efficientdet_lite0.tflite')

PL = vision.PoseLandmark
CONNECTIONS = [(c.start, c.end) for c in vision.PoseLandmarksConnections.POSE_LANDMARKS]

try:
  font_path = '/System/Library/Fonts/STHeiti Light.ttc'
  font_large = ImageFont.truetype(font_path, 40)
  font_medium = ImageFont.truetype(font_path, 30)
  font_small = ImageFont.truetype(font_path, 20)
except:
  font_large = font_medium = font_small = ImageFont.load_default()

def draw_chinese_text(img, text, pos, font, color=(255, 255, 255)):
  """color 採用跟專案其他畫面元素(cv2.rectangle 等)一致的 BGR 順序。

  PIL 的 fill 參數是 RGB,這裡轉換成 RGB 繪製後再轉回 BGR 輸出,
  若直接把呼叫端的 BGR tuple 原封不動傳給 PIL,R/B 色版會對調
  (例如原本想畫紅色 (0,0,255) 會變成畫出藍色)。
  """
  img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
  rgb_color = (color[2], color[1], color[0])
  ImageDraw.Draw(img_pil).text(pos, text, font=font, fill=rgb_color)
  return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

def enhance_image(frame):
  denoised = cv2.bilateralFilter(frame, 9, 75, 75)
  lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
  l, a, b = cv2.split(lab)
  clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
  l = clahe.apply(l)
  enhanced = cv2.merge([l, a, b])
  return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

def create_pose_landmarker():
  options = vision.PoseLandmarkerOptions(
      base_options=BaseOptions(model_asset_path=POSE_MODEL_PATH),
      running_mode=vision.RunningMode.IMAGE,
      num_poses=1,
      min_pose_detection_confidence=0.01,
      min_pose_presence_confidence=0.01,
      min_tracking_confidence=0.01,
  )
  return vision.PoseLandmarker.create_from_options(options)

def create_object_detector():
  """建立物種過濾用的物體偵測器,僅接受 COCO 的 'person' 類別。

  用來在姿態估計前先鎖定畫面中「人」的區域,排除貓狗等其他物種
  (PoseLandmarker 本身不分物種,任何輸入都會硬擠出一組人體關鍵點猜測)。
  """
  options = vision.ObjectDetectorOptions(
      base_options=BaseOptions(model_asset_path=OBJECT_MODEL_PATH),
      running_mode=vision.RunningMode.IMAGE,
      score_threshold=0.4,
      category_allowlist=['person'],
      max_results=5,
  )
  return vision.ObjectDetector.create_from_options(options)

def detect_largest_person_box(object_detector, frame, fh, fw):
  """用物體偵測鎖定畫面中最大的「person」框,非人物種不會被鎖定為 ROI。"""
  enhanced = enhance_image(frame)
  rgb = cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)
  mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
  result = object_detector.detect(mp_image)

  if not result.detections:
    return None

  boxes = []
  for det in result.detections:
    bbox = det.bounding_box
    x1, y1 = bbox.origin_x, bbox.origin_y
    x2, y2 = x1 + bbox.width, y1 + bbox.height
    boxes.append((x1, y1, x2, y2))

  return max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))

def is_human_skeleton(raw_points):
  try:
    ls = raw_points.get(PL.LEFT_SHOULDER)
    rs = raw_points.get(PL.RIGHT_SHOULDER)
    lh = raw_points.get(PL.LEFT_HIP)
    rh = raw_points.get(PL.RIGHT_HIP)
    le = raw_points.get(PL.LEFT_ELBOW)
    re = raw_points.get(PL.RIGHT_ELBOW)
    lw = raw_points.get(PL.LEFT_WRIST)
    rw = raw_points.get(PL.RIGHT_WRIST)
    lk = raw_points.get(PL.LEFT_KNEE)
    rk = raw_points.get(PL.RIGHT_KNEE)
    la = raw_points.get(PL.LEFT_ANKLE)
    ra = raw_points.get(PL.RIGHT_ANKLE)

    if not all([ls, rs, lh, rh]):
      return False

    def dist(p1, p2):
      return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

    shoulder_w = dist(ls, rs)
    hip_w = dist(lh, rh)
    if hip_w > shoulder_w * 2.0:
      return False

    # 註：原本要求 shoulder_to_hip(肩髖垂直距離) >= shoulder_w * 0.3,
    # 但人躺平/倒地時肩髖幾乎在同一水平線上,垂直距離趨近 0,
    # 會被這條規則誤判為「非人體骨架」而完全濾掉跌倒姿態。已移除此限制。

    if le and lw:
      upper_arm_l = dist(ls, le)
      lower_arm_l = dist(le, lw)
      if lower_arm_l > 0.1 and upper_arm_l > 0.1:
        arm_ratio = lower_arm_l / upper_arm_l
        if arm_ratio < 0.15 or arm_ratio > 4.0:
          return False

    if re and rw:
      upper_arm_r = dist(rs, re)
      lower_arm_r = dist(re, rw)
      if lower_arm_r > 0.1 and upper_arm_r > 0.1:
        arm_ratio = lower_arm_r / upper_arm_r
        if arm_ratio < 0.15 or arm_ratio > 4.0:
          return False

    if lk and la:
      upper_leg_l = dist(lh, lk)
      lower_leg_l = dist(lk, la)
      if lower_leg_l > 0.1 and upper_leg_l > 0.1:
        leg_ratio = lower_leg_l / upper_leg_l
        if leg_ratio < 0.15 or leg_ratio > 3.0:
          return False

    if rk and ra:
      upper_leg_r = dist(rh, rk)
      lower_leg_r = dist(rk, ra)
      if lower_leg_r > 0.1 and upper_leg_r > 0.1:
        leg_ratio = lower_leg_r / upper_leg_r
        if leg_ratio < 0.15 or leg_ratio > 3.0:
          return False

    # 躺姿/側身時肩膀左右高度差會變大,原本 0.5 倍過嚴,放寬到 1.5 倍
    left_shoulder_y = ls[1]
    right_shoulder_y = rs[1]
    if abs(left_shoulder_y - right_shoulder_y) > shoulder_w * 1.5:
      return False

    return True
  except:
    return False

def detect_skeleton_in_roi(landmarker, frame, fh, fw, roi):
  if roi is None:
    return frame, None

  x1, y1, x2, y2 = roi
  crop = frame[y1:y2, x1:x2]
  ch, cw = crop.shape[:2]

  if ch < 50 or cw < 50:
    return frame, None

  enhanced_crop = enhance_image(crop)
  rgb = cv2.cvtColor(enhanced_crop, cv2.COLOR_BGR2RGB)
  mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
  result = landmarker.detect(mp_image)

  if not result.pose_landmarks:
    return frame, None

  lm = result.pose_landmarks[0]
  raw_points = {}

  for i in range(len(lm)):
    p = lm[i]
    if p.visibility is not None and p.visibility < 0.05:
      continue
    px = x1 + int(p.x * cw)
    py = y1 + int(p.y * ch)
    raw_points[i] = (px, py)

  if not is_human_skeleton(raw_points):
    return frame, None

  for a, b in CONNECTIONS:
    if a in raw_points and b in raw_points:
      cv2.line(frame, raw_points[a], raw_points[b], (0, 255, 255), 2)

  for p in raw_points.values():
    cv2.circle(frame, p, 3, (0, 255, 0), -1)

  return frame, raw_points

def detect_fall(raw_points):
  if not raw_points or len(raw_points) < 6:
    return False

  try:
    width, height = bbox_dims(raw_points)

    if height < 1e-5:
      return False

    # 核心判斷依據:骨架整體 bounding box 的寬高比。
    # 站立(含彎腰、雙腳自然分開)時人體仍是瘦高的(height >> width);
    # 躺平/倒地時人體橫向攤開(width 接近或超過 height)。
    # 這比「肩髖連線角度」更穩健,不會被雙腳分開站立、輕微側身誤觸發。
    aspect_ratio = width / height
    if aspect_ratio > 1.0:
      return True

    ls = raw_points.get(PL.LEFT_SHOULDER)
    rs = raw_points.get(PL.RIGHT_SHOULDER)
    lh = raw_points.get(PL.LEFT_HIP)
    rh = raw_points.get(PL.RIGHT_HIP)

    if all([ls, rs, lh, rh]):
      shoulder_x = (ls[0] + rs[0]) / 2
      shoulder_y = (ls[1] + rs[1]) / 2
      hip_x = (lh[0] + rh[0]) / 2
      hip_y = (lh[1] + rh[1]) / 2
      dx = hip_x - shoulder_x
      dy = hip_y - shoulder_y
      angle = math.degrees(math.atan2(abs(dx), abs(dy) + 1e-5))

      # 輔助判斷:軀幹嚴重傾倒(角度大)且身形已明顯變寬時才算跌倒,
      # 避免單靠角度在彎腰/側身時誤報。
      if angle > 60 and aspect_ratio > 0.7:
        return True

    return False

  except:
    return False

MOTION_WINDOW_SECONDS = 1.0    # 計算速度用的取樣時間窗口
MOTION_STALE_SECONDS = 1.5     # 樣本間隔超過這麼久視為不連續(骨架斷過久),整批捨棄重新累積
MOTION_MIN_DT = 0.05           # 時間差太小則跳過,避免雜訊放大成離譜的速度值
MOTION_VELOCITY_THRESHOLD = 2.0  # 下墜速度門檻,單位:身高(bbox 高度)/秒
MOTION_ACCEL_THRESHOLD = 4.0     # 下墜加速度門檻,單位:身高/秒^2

def bbox_dims(raw_points):
  xs = [p[0] for p in raw_points.values()]
  ys = [p[1] for p in raw_points.values()]
  return max(xs) - min(xs), max(ys) - min(ys)

def skeleton_bbox(raw_points, fh, fw, margin=50):
  """用骨架點的 bounding box(往外擴 margin)取代物件偵測框,
  讓 ROI 能跟著人實際的姿態/位置走,而不是卡在物件偵測器最後一次
  成功鎖定的舊位置(跌倒後物件偵測器常常認不出趴姿的「person」)。
  """
  xs = [p[0] for p in raw_points.values()]
  ys = [p[1] for p in raw_points.values()]
  x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
  return (max(0, x1 - margin), max(0, y1 - margin), min(fw, x2 + margin), min(fh, y2 + margin))

class MotionTracker:
  """用實際時間差(而非幀數)追蹤骨架中心點的下墜速度/加速度。

  卡頓造成的不固定 dt 會直接反映在算出的速度裡而不會失真;若中間斷點
  過久(骨架長時間抓丟)則捨棄舊樣本重新累積,避免用隔太久的兩點硬算速度。
  """

  def __init__(self):
    self.samples = deque()  # (timestamp, center_y, body_height)
    self.last_velocity = None  # (timestamp, velocity_y)

  def reset(self):
    self.samples.clear()
    self.last_velocity = None

  def update(self, raw_points, now):
    if not raw_points or len(raw_points) < 4:
      return False

    ls = raw_points.get(PL.LEFT_SHOULDER)
    rs = raw_points.get(PL.RIGHT_SHOULDER)
    lh = raw_points.get(PL.LEFT_HIP)
    rh = raw_points.get(PL.RIGHT_HIP)
    torso_pts = [p for p in (ls, rs, lh, rh) if p]
    if len(torso_pts) < 2:
      return False

    _, height = bbox_dims(raw_points)
    if height < 1e-5:
      return False

    center_y = sum(p[1] for p in torso_pts) / len(torso_pts)

    if self.samples and (now - self.samples[-1][0]).total_seconds() > MOTION_STALE_SECONDS:
      self.reset()

    self.samples.append((now, center_y, height))
    while self.samples and (now - self.samples[0][0]).total_seconds() > MOTION_WINDOW_SECONDS:
      self.samples.popleft()

    if len(self.samples) < 2:
      return False

    t0, y0, h0 = self.samples[0]
    t1, y1, h1 = self.samples[-1]
    dt = (t1 - t0).total_seconds()
    if dt < MOTION_MIN_DT:
      return False

    avg_h = (h0 + h1) / 2.0
    velocity_y = ((y1 - y0) / dt) / avg_h  # 正值代表往下墜落(影像 y 軸向下為正)

    is_fast_fall = velocity_y > MOTION_VELOCITY_THRESHOLD

    accel_triggered = False
    if self.last_velocity is not None:
      pt, pv = self.last_velocity
      dvt = (t1 - pt).total_seconds()
      if dvt >= MOTION_MIN_DT:
        accel = (velocity_y - pv) / dvt
        if velocity_y > 0 and accel > MOTION_ACCEL_THRESHOLD:
          accel_triggered = True

    self.last_velocity = (t1, velocity_y)

    return is_fast_fall or accel_triggered

_VLLM_PENDING = object()  # 尚未有結果回來的佔位值,跟 confirm_fall() 合法回傳的 None(連線失敗)區分開來

class VllmChecker:
  """在背景執行緒呼叫 vLLM 二次確認,不阻塞主迴圈畫面更新。

  confirm_fall() 是同步的 HTTP 請求,直接在主迴圈呼叫會讓畫面卡住等待回應。
  這裡改成丟給背景執行緒跑,主迴圈只需要每幀「問一下有沒有結果」(poll),
  讓跌倒倒數可以立刻開始、画面不被擋住,vLLM 的結果晚一點回來再補判斷。
  """

  def __init__(self):
    self.box = None  # None=目前沒有在跑;[_VLLM_PENDING]=執行中;[result]=有結果等著被讀取
    self.last_started = None

  def maybe_start(self, frame, now, cooldown):
    if self.box is not None and self.box[0] is _VLLM_PENDING:
      return  # 上一次還沒回來,不要疊加呼叫
    if self.last_started is not None and (now - self.last_started).total_seconds() < cooldown:
      return
    self.last_started = now
    box = [_VLLM_PENDING]
    snapshot = frame.copy()

    def _run():
      box[0] = confirm_fall(snapshot, VLLM_BASE_URL, VLLM_MODEL)

    threading.Thread(target=_run, daemon=True).start()
    self.box = box

  def poll(self):
    """有新結果就回傳並清空;還在等就回傳 _VLLM_PENDING。"""
    if self.box is None or self.box[0] is _VLLM_PENDING:
      return _VLLM_PENDING
    result = self.box[0]
    self.box = None
    return result

  def reset(self):
    self.box = None
    self.last_started = None

def send_alert(ts):
  """回傳是否「真的」推播成功(家屬/119 有收到),不是單純送出請求就算數。"""
  try:
    response = requests.post(FLASK_API_URL, json={'event': 'fall_5s_confirmed', 'time': ts, 'confidence': 0.90}, timeout=5)
    delivered = bool(response.json().get('alert_sent'))
    if delivered:
      print('警報已送出,且已確認推播給家屬')
    else:
      print('警報已送出,但尚未確認有實際推播給家屬')
    return delivered
  except Exception as e:
    print(f'警報送出失敗:{e}')
    return False

def main(source=0):
  is_file_source = isinstance(source, str)
  print('獨居長者跌倒偵測系統（圖像增強+人體解剖驗證）')
  print(f'輸入來源:{"檔案 " + source if is_file_source else "攝影機"}')
  print('按 q 離開 | 按 r 重置 | 按 c 重新鎖定\n')

  cap = cv2.VideoCapture(source)
  if not cap.isOpened():
    print('無法開啟輸入來源')
    return

  if not is_file_source:
    cap.set(cv2.CAP_PROP_FPS, 60)

  fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
  fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
  prev_tick = time.perf_counter()
  display_fps = 0.0

  landmarker = create_pose_landmarker()
  object_detector = create_object_detector()
  fc, fall_time, reported, fall_cnt = 0, None, False, 0
  alert_delivered = False
  last_fall_seen_time = None
  vllm_checker = VllmChecker()
  vllm_veto_checked = False
  roi = None
  roi_lock_frame = 0
  motion_tracker = MotionTracker()
  motion_seen_during_fall = False
  last_motion_fall_time = None
  GRACE_PERIOD_SECONDS = 3.0  # 進入跌倒狀態後,允許中斷(掙扎/暫時抓不到骨架)的最大容忍秒數
  EXTENDED_GRACE_PERIOD_SECONDS = 10.0  # 若倒下瞬間有偵測到明確的下墜動態,代表真的發生過快速倒下,
  # 之後即使朝鏡頭方向倒地(躺平後寬高比仍是「窄高」,偵測不到)也放寬容忍時間,不要太快判定「起身」
  MOTION_TRIGGER_WINDOW_SECONDS = 10.0  # 偵測到快速下墜動態後,這段時間內持續嘗試 vLLM 確認,
  # 不必等寬高比連續 5 幀穩定達標,避免倒下瞬間畫面模糊/角度不佳被 vLLM 拒絕一次就永久錯過
  FALL_CONFIRM_SECONDS = 10.0  # 跌倒狀態持續多久才確認送出警報

  while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
      break

    if not is_file_source:
      frame = cv2.flip(frame, 1)

    tick = time.perf_counter()
    frame_dt = tick - prev_tick
    prev_tick = tick
    if frame_dt > 0:
      display_fps = display_fps * 0.9 + (1.0 / frame_dt) * 0.1  # 指數移動平均,避免數字跳動太快

    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    fc += 1

    if roi is None or (fc - roi_lock_frame) % 30 == 0:
      new_roi = detect_largest_person_box(object_detector, frame, fh, fw)
      if new_roi:
        roi_lock_frame = fc
        x1, y1, x2, y2 = new_roi
        roi = (max(0, x1-50), max(0, y1-50), min(fw, x2+50), min(fh, y2+50))
      # 物件偵測器這次沒找到「person」(例如趴姿信心分數不足)時,
      # 沿用上一次鎖定的區域繼續嘗試姿態偵測,不整個放棄清空,
      # 避免趴姿造成 ROI 中斷太久而被寬容期誤判為「起身」

    frame, raw_points = detect_skeleton_in_roi(landmarker, frame, fh, fw, roi)

    if raw_points:
      roi = skeleton_bbox(raw_points, fh, fw)

    pose_is_fall = detect_fall(raw_points) if raw_points else False
    motion_is_fall = motion_tracker.update(raw_points, now)
    is_fall = pose_is_fall or motion_is_fall

    if motion_is_fall:
      motion_seen_during_fall = True
      last_motion_fall_time = now

    if is_fall:
      last_fall_seen_time = now

    fall_cnt = (fall_cnt + 1) if is_fall else 0
    stable = fall_cnt >= 5
    motion_recently_seen = (
        last_motion_fall_time is not None
        and (now - last_motion_fall_time).total_seconds() <= MOTION_TRIGGER_WINDOW_SECONDS
    )

    # 尚未進入跌倒狀態時,寬高比連續穩定達標,或是最近偵測過明確的下墜動態,
    # 就立刻進入倒數狀態(不等 vLLM 回應,避免同步呼叫擋住畫面造成卡頓)。
    # vLLM 二次確認改在背景執行緒跑,晚一點用 vllm_veto_checked 那段邏輯補判斷:
    # 如果確認是「非跌倒」才取消這次警報,等於是事後否決,不是事前阻擋。
    if (stable or motion_recently_seen) and fall_time is None:
      fall_time = now
      vllm_veto_checked = False
      vllm_checker.reset()
      vllm_checker.maybe_start(frame, now, VLLM_COOLDOWN_SECONDS)
      print(f'{now_str} 偵測到跌倒(MediaPipe 判斷),開始倒數,背景執行 vLLM 二次確認中...')

    if fall_time is not None and not reported and not vllm_veto_checked:
      vllm_result = vllm_checker.poll()
      if vllm_result is _VLLM_PENDING:
        vllm_checker.maybe_start(frame, now, VLLM_COOLDOWN_SECONDS)
      else:
        vllm_veto_checked = True
        if vllm_result is False:
          # vLLM 事後否決,取消這次警報(不阻塞畫面,但仍然保有二次確認的把關效果)
          print(f'{now_str} vLLM 二次確認為非跌倒,取消本次警報')
          fall_time, reported, fall_cnt = None, False, 0
          alert_delivered = False
        elif vllm_result is None:
          print(f'{now_str} vLLM 無法連線,退回 MediaPipe 單獨判斷')
        else:
          print(f'{now_str} vLLM 二次確認通過(雙重確認)')

    if fall_time is not None:
      # 已進入跌倒狀態:掙扎/移動導致暫時偵測不到跌倒姿態(甚至骨架抓不到)
      # 不算解除,只有連續超過寬容期都沒再偵測到才視為真正起身。
      # 若倒下瞬間確實偵測到快速下墜的動態訊號(motion_seen_during_fall),
      # 代表這是真的跌倒(可能朝鏡頭方向倒地,躺平後寬高比判斷不出來),
      # 用延長過的寬容期,避免太快被誤判成起身
      effective_grace_period = EXTENDED_GRACE_PERIOD_SECONDS if motion_seen_during_fall else GRACE_PERIOD_SECONDS
      since_last_seen = (now - last_fall_seen_time).total_seconds() if last_fall_seen_time else effective_grace_period + 1

      if since_last_seen > effective_grace_period:
        print(f'{now_str} 跌倒狀態解除(起身)')
        fall_time, reported, fall_cnt = None, False, 0
        motion_seen_during_fall = False
        last_motion_fall_time = None
        alert_delivered = False
        vllm_veto_checked = False
        vllm_checker.reset()
        frame = draw_chinese_text(frame, '正常', (20, 40), font_large, (0, 255, 0))
      else:
        elapsed = (now - fall_time).total_seconds()
        remaining = max(0, FALL_CONFIRM_SECONDS - elapsed)

        if elapsed >= FALL_CONFIRM_SECONDS and not reported:
          reported = True
          print(f'跌倒狀態已持續超過 {FALL_CONFIRM_SECONDS:.0f} 秒，確認警報!')
          alert_delivered = send_alert(now_str)

        if reported and alert_delivered:
          # 已經「確定」推播成功給家屬/119(不是單純送出請求),才切換顯示文字
          frame = draw_chinese_text(frame, '危險 已推播至家屬及119', (20, 40), font_large, (0, 0, 255))
        elif reported:
          # 倒數已結束、警報已送出但推播未確認成功:不要再顯示「倒數 0.0 秒」誤導成沒在倒數
          frame = draw_chinese_text(frame, '危險 - 偵測到跌倒', (20, 40), font_large, (0, 0, 255))
          frame = draw_chinese_text(frame, '警報已送出(推播未確認)', (20, 95), font_medium, (0, 0, 255))
        else:
          frame = draw_chinese_text(frame, '危險 - 偵測到跌倒', (20, 40), font_large, (0, 0, 255))
          frame = draw_chinese_text(frame, f'倒數計時：{remaining:.1f} 秒', (20, 95), font_medium, (0, 0, 255))
    else:
      frame = draw_chinese_text(frame, '正常', (20, 40), font_large, (0, 255, 0))

    if roi:
      x1, y1, x2, y2 = roi
      cv2.rectangle(frame, (x1, y1), (x2, y2), (100, 100, 255), 2)

    frame = draw_chinese_text(frame, now_str, (fw - 400, 20), font_large, (255, 255, 255))
    frame = draw_chinese_text(frame, f'FPS: {display_fps:.1f}', (fw - 280, 70), font_medium, (255, 255, 255))
    cv2.imshow('Fall Detection', frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
      break
    elif key == ord('r'):
      fall_time, reported, fall_cnt = None, False, 0
      motion_seen_during_fall = False
      last_motion_fall_time = None
      alert_delivered = False
      vllm_veto_checked = False
      vllm_checker.reset()
      motion_tracker.reset()
    elif key == ord('c'):
      roi = None
      motion_tracker.reset()
      print('重新鎖定位置...')

  landmarker.close()
  object_detector.close()
  cap.release()
  cv2.destroyAllWindows()
  print('系統已關閉')

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='獨居長者跌倒偵測系統')
  parser.add_argument('--source', type=str, default=None, help='影片檔案路徑,不指定則使用攝影機')
  args = parser.parse_args()
  main(args.source if args.source else 0)
