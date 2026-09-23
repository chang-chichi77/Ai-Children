#!/usr/bin/env python3
import math
import os
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
  font_large = ImageFont.truetype(font_path, 32)
  font_medium = ImageFont.truetype(font_path, 24)
  font_small = ImageFont.truetype(font_path, 16)
except:
  font_large = font_medium = font_small = ImageFont.load_default()

def draw_chinese_text(img, text, pos, font, color=(255, 255, 255)):
  img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
  ImageDraw.Draw(img_pil).text(pos, text, font=font, fill=color)
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
      score_threshold=0.3,
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
    xs = [p[0] for p in raw_points.values()]
    ys = [p[1] for p in raw_points.values()]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

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

def send_alert(ts):
  try:
    requests.post(FLASK_API_URL, json={'event': 'fall_10s_confirmed', 'time': ts, 'confidence': 0.90}, timeout=5)
    print('警報已送出')
    return True
  except Exception as e:
    print(f'警報送出失敗:{e}')
    return False

def main():
  print('獨居長者跌倒偵測系統（圖像增強+人體解剖驗證）')
  print('按 q 離開 | 按 r 重置 | 按 c 重新鎖定\n')

  cap = cv2.VideoCapture(0)
  if not cap.isOpened():
    print('無法開啟攝影機')
    return

  fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
  fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

  landmarker = create_pose_landmarker()
  object_detector = create_object_detector()
  fc, fall_time, reported, fall_cnt = 0, None, False, 0
  last_fall_seen_time = None
  last_vllm_check_time = None
  roi = None
  roi_lock_frame = 0
  GRACE_PERIOD_SECONDS = 3.0  # 進入跌倒狀態後,允許中斷(掙扎/暫時抓不到骨架)的最大容忍秒數

  while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
      break

    frame = cv2.flip(frame, 1)
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    fc += 1

    if roi is None or (fc - roi_lock_frame) % 30 == 0:
      roi = detect_largest_person_box(object_detector, frame, fh, fw)
      if roi:
        roi_lock_frame = fc
        x1, y1, x2, y2 = roi
        roi = (max(0, x1-50), max(0, y1-50), min(fw, x2+50), min(fh, y2+50))

    frame, raw_points = detect_skeleton_in_roi(landmarker, frame, fh, fw, roi)
    is_fall = detect_fall(raw_points) if raw_points else False

    if is_fall:
      last_fall_seen_time = now

    fall_cnt = (fall_cnt + 1) if is_fall else 0
    stable = fall_cnt >= 5

    # 尚未進入跌倒狀態時,需連續穩定偵測到才觸發,避免單幀誤判
    if stable and fall_time is None:
      can_check_vllm = (
          last_vllm_check_time is None
          or (now - last_vllm_check_time).total_seconds() > VLLM_COOLDOWN_SECONDS
      )
      if can_check_vllm:
        last_vllm_check_time = now
        vllm_result = confirm_fall(frame, VLLM_BASE_URL, VLLM_MODEL)
        if vllm_result is False:
          # vLLM 明確判斷非跌倒/非人,暫不觸發,冷卻時間內不重複呼叫
          print(f'{now_str} MediaPipe 疑似跌倒,但 vLLM 二次確認為非跌倒,暫不觸發')
        else:
          fall_time = now
          if vllm_result is None:
            print(f'{now_str} 偵測到跌倒(vLLM 無法連線,退回 MediaPipe 單獨判斷)')
          else:
            print(f'{now_str} 偵測到跌倒(MediaPipe + vLLM 雙重確認)')

    if fall_time is not None:
      # 已進入跌倒狀態:掙扎/移動導致暫時偵測不到跌倒姿態(甚至骨架抓不到)
      # 不算解除,只有連續超過寬容期都沒再偵測到才視為真正起身
      since_last_seen = (now - last_fall_seen_time).total_seconds() if last_fall_seen_time else GRACE_PERIOD_SECONDS + 1

      if since_last_seen > GRACE_PERIOD_SECONDS:
        print(f'{now_str} 跌倒狀態解除(起身)')
        fall_time, reported, fall_cnt = None, False, 0
        frame = draw_chinese_text(frame, '正常', (20, 40), font_large, (0, 255, 0))
      else:
        elapsed = (now - fall_time).total_seconds()
        remaining = max(0, 10 - elapsed)

        if elapsed >= 10 and not reported:
          reported = True
          print('跌倒狀態已持續超過 10 秒，確認警報!')
          send_alert(now_str)

        frame = draw_chinese_text(frame, '危險 - 偵測到跌倒', (20, 40), font_large, (0, 0, 255))
        frame = draw_chinese_text(frame, f'倒數計時：{remaining:.1f} 秒', (20, 80), font_medium, (0, 0, 255))
    else:
      frame = draw_chinese_text(frame, '正常', (20, 40), font_large, (0, 255, 0))

    if roi:
      x1, y1, x2, y2 = roi
      cv2.rectangle(frame, (x1, y1), (x2, y2), (100, 100, 255), 2)

    frame = draw_chinese_text(frame, now_str, (fw - 280, 20), font_medium, (255, 255, 255))
    cv2.imshow('Fall Detection', frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
      break
    elif key == ord('r'):
      fall_time, reported, fall_cnt = None, False, 0
    elif key == ord('c'):
      roi = None
      print('重新鎖定位置...')

  landmarker.close()
  object_detector.close()
  cap.release()
  cv2.destroyAllWindows()
  print('系統已關閉')

if __name__ == '__main__':
  main()
