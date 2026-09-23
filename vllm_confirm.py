"""vLLM 二次確認模組 - 改寫自 fall_detect_v1.0.0/fall_detector.py。

MediaPipe 判定「疑似跌倒」後,截取當下畫面送往本地 vLLM(OpenAI 相容 API)
多模態模型做二次確認,降低單靠姿態幾何規則造成的誤判。

與原版 fall_detector.py 的差異:
- 原版讀取圖片檔案路徑,本版直接接收 OpenCV frame(numpy array),
  避免即時視訊場景下還要先寫檔案再讀檔的額外 I/O。
- 原版輸出固定格式字串,本版額外提供 `is_fall_confirmed()` 布林介面,
  方便 detector.py 直接使用。
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

import cv2
import requests

from logger import get_logger

DEFAULT_BASE_URL = os.environ.get("FALL_DETECT_BASE_URL", "http://10.0.0.206:8010/v1")
DEFAULT_MODEL = os.environ.get("FALL_DETECT_MODEL", "gemma-4-26b")
REQUEST_TIMEOUT_SECONDS = 5  # 即時視訊場景不能等太久,逾時就退回 MediaPipe 單獨判斷
TEMPERATURE = 0.0
MAX_TOKENS = 200

PROMPT_FILE_PATH = Path(os.environ.get(
    "FALL_DETECT_PROMPT_FILE",
    str(Path(__file__).resolve().parent / "prompts" / "fall_detect_prompt.md"),
))
PROMPT_SYSTEM_MARKER = "<!-- system_prompt -->"
PROMPT_USER_MARKER = "<!-- user_prompt -->"

FallStatus = Literal["fallen", "not_fallen", "uncertain"]
FALL_STATUS_VALUES: tuple[str, ...] = get_args(FallStatus)

RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_person": {"type": "boolean"},
        "fall_status": {"type": "string", "enum": list(FALL_STATUS_VALUES)},
    },
    "required": ["is_person", "fall_status"],
}

logger = get_logger(__name__)

_cached_prompts: tuple[str, str] | None = None


@dataclass
class DetectionResult:
    is_person: bool
    fall_status: FallStatus


def load_prompts(prompt_path: Path = PROMPT_FILE_PATH) -> tuple[str, str]:
    """讀取並快取 system/user prompt,避免每次呼叫都重新讀檔。"""
    global _cached_prompts
    if _cached_prompts is not None:
        return _cached_prompts

    text = prompt_path.read_text(encoding="utf-8")
    if PROMPT_SYSTEM_MARKER not in text or PROMPT_USER_MARKER not in text:
        raise ValueError(f"prompt 檔案缺少必要區塊標記: {prompt_path}")

    system_part = text.split(PROMPT_SYSTEM_MARKER, 1)[1].split(PROMPT_USER_MARKER, 1)[0].strip()
    user_part = text.split(PROMPT_USER_MARKER, 1)[1].strip()

    if not system_part or not user_part:
        raise ValueError(f"prompt 檔案區塊內容為空: {prompt_path}")

    _cached_prompts = (system_part, user_part)
    return _cached_prompts


def encode_frame_to_data_url(frame) -> str:
    """將 OpenCV frame(BGR numpy array)編碼為 OpenAI 格式的 data URL。"""
    success, buffer = cv2.imencode(".jpg", frame)
    if not success:
        raise ValueError("frame 編碼為 JPEG 失敗")
    encoded = base64.b64encode(buffer).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def build_request_payload(
    data_url: str, model: str, system_prompt: str, user_prompt: str
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "fall_detection_result",
                "schema": RESPONSE_JSON_SCHEMA,
            },
        },
    }


def call_vllm(
    data_url: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    system_prompt: str = "",
    user_prompt: str = "",
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = build_request_payload(data_url, model, system_prompt, user_prompt)
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def parse_response(response_json: dict[str, Any]) -> DetectionResult | None:
    try:
        content = response_json["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        is_person = bool(parsed["is_person"])
        fall_status = parsed["fall_status"]
        if fall_status not in FALL_STATUS_VALUES:
            raise ValueError(f"fall_status 不在允許範圍內: {fall_status!r}")
        return DetectionResult(is_person=is_person, fall_status=fall_status)
    except (KeyError, IndexError, TypeError) as exc:
        logger.exception("API 回應結構不符預期: %s", exc)
        return None
    except json.JSONDecodeError as exc:
        logger.exception("模型回傳內容非合法 JSON: %s", exc)
        return None
    except ValueError as exc:
        logger.exception("模型回傳 fall_status 值不合法: %s", exc)
        return None


def confirm_fall(
    frame,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
) -> bool | None:
    """對單一畫面呼叫 vLLM 做跌倒二次確認。

    Returns:
        True: vLLM 確認是人且已跌倒。
        False: vLLM 確認是人但未跌倒,或確認不是人。
        None: 呼叫失敗(逾時/連線錯誤/回應不合法),代表「無法確認」,
              呼叫端應自行決定 fallback 策略(通常是退回只用 MediaPipe 判斷)。
    """
    try:
        system_prompt, user_prompt = load_prompts()
    except (FileNotFoundError, ValueError):
        logger.exception("讀取 prompt 檔案失敗,無法呼叫 vLLM 做二次確認")
        return None

    try:
        data_url = encode_frame_to_data_url(frame)
        response_json = call_vllm(data_url, base_url, model, system_prompt, user_prompt)
    except requests.RequestException:
        logger.warning("呼叫 vLLM API 失敗(可能離線或逾時),退回 MediaPipe 單獨判斷")
        return None
    except ValueError:
        logger.exception("frame 編碼失敗")
        return None

    detection = parse_response(response_json)
    if detection is None:
        return None
    if not detection.is_person:
        return False
    return detection.fall_status == "fallen"
