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

load_dotenv()

FLASK_API_URL = 'http://127.0.0.1:5002/api/fall_event'
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'pose_landmarker_lite.task')

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

def create_pose_landmarker():
  options = vision.PoseLandmarkerOptions(
      base_options=BaseOptions(model_asset_path=MODEL_PATH),
      running_mode=vision.RunningMode.VIDEO,
      num_poses=1,
      min_pose_detection_confidence=0.5,
      min_pose_presence_confidence=0.5,
      min_tracking_confidence=0.5,
  )
  return vision.PoseLandmarker.create_from_options(options)

def detect_skeleton(landmarker, frame, fh, fw, timestamp_ms):
  rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
  mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
  result = landmarker.detect_for_video(mp_image, timestamp_ms)

  if not result.pose_landmarks:
    return frame, {}

  lm = result.pose_landmarks[0]

  def px(idx):
    p = lm[idx]
    if p.visibility is not None and p.visibility < 0.3:
      return None
    return (int(p.x * fw), int(p.y * fh))

  for a, b in CONNECTIONS:
    pa, pb = px(a), px(b)
    if pa and pb:
      cv2.line(frame, pa, pb, (0, 255, 255), 2)

  for i in range(len(lm)):
    p = px(i)
    if p:
      cv2.circle(frame, p, 3, (0, 255, 0), -1)

  points = {
      'nose': px(PL.NOSE),
      'left_shoulder': px(PL.LEFT_SHOULDER), 'right_shoulder': px(PL.RIGHT_SHOULDER),
      'left_hip': px(PL.LEFT_HIP), 'right_hip': px(PL.RIGHT_HIP),
      'left_knee': px(PL.LEFT_KNEE), 'right_knee': px(PL.RIGHT_KNEE),
      'left_ankle': px(PL.LEFT_ANKLE), 'right_ankle': px(PL.RIGHT_ANKLE),
  }
  points = {k: v for k, v in points.items() if v is not None}

  return frame, points

def _midpoint(p1, p2):
  return ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)

def _torso_angle_from_vertical(shoulder_mid, hip_mid):
  dx = hip_mid[0] - shoulder_mid[0]
  dy = hip_mid[1] - shoulder_mid[1]
  angle = math.degrees(math.atan2(abs(dx), abs(dy) + 1e-5))
  return angle

def detect_fall(points):
  required = ('left_shoulder', 'right_shoulder', 'left_hip', 'right_hip')
  if not all(k in points for k in required):
    return False
  try:
    shoulder_mid = _midpoint(points['left_shoulder'], points['right_shoulder'])
    hip_mid = _midpoint(points['left_hip'], points['right_hip'])

    torso_angle = _torso_angle_from_vertical(shoulder_mid, hip_mid)
    is_horizontal_torso = torso_angle > 55

    hip_below_shoulder = hip_mid[1] > shoulder_mid[1]

    return is_horizontal_torso and hip_below_shoulder
  except:
    return False

def send_alert(ts):
  try:
    requests.post(FLASK_API_URL, json={'event': 'fall_10s_confirmed', 'time': ts, 'confidence': 0.90}, timeout=5)
    print(f'警報已送出')
    return True
  except Exception as e:
    print(f'警報送出失敗：{e}')
    return False

def main():
  print('獨居長者跌倒偵測系統')
  print('按 q 離開 | 按 r 重置\n')

  cap = cv2.VideoCapture(0)
  if not cap.isOpened():
    print('無法開啟攝影機')
    return

  fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
  fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

  landmarker = create_pose_landmarker()
  fc, fall_time, reported, fall_cnt = 0, None, False, 0

  while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
      break

    frame = cv2.flip(frame, 1)
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    fc += 1
    timestamp_ms = fc * (1000 // 30)

    frame, pts = detect_skeleton(landmarker, frame, fh, fw, timestamp_ms)
    is_fall = detect_fall(pts)

    fall_cnt = (fall_cnt + 1) if is_fall else 0
    stable = fall_cnt >= 5

    if stable:
      if not fall_time:
        fall_time = now
        print(f'{now_str} 偵測到跌倒')

      elapsed = (now - fall_time).total_seconds()
      remaining = max(0, 10 - elapsed)

      if elapsed >= 10 and not reported:
        reported = True
        print(f'跌倒狀態已持續超過 10 秒，確認警報！')
        send_alert(now_str)

      frame = draw_chinese_text(frame, '危險 - 偵測到跌倒', (20, 40), font_large, (0, 0, 255))
      frame = draw_chinese_text(frame, f'倒數計時：{remaining:.1f} 秒', (20, 80), font_medium, (0, 0, 255))
    else:
      if fall_time:
        print(f'{now_str} 跌倒狀態解除')
      fall_time, reported = None, False
      frame = draw_chinese_text(frame, '正常', (20, 40), font_large, (0, 255, 0))

    frame = draw_chinese_text(frame, now_str, (fw - 280, 20), font_medium, (255, 255, 255))
    cv2.imshow('Fall Detection', frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
      break
    elif key == ord('r'):
      fall_time, reported, fall_cnt = None, False, 0

  landmarker.close()
  cap.release()
  cv2.destroyAllWindows()
  print('系統已關閉')

if __name__ == '__main__':
  main()
