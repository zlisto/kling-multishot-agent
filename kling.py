"""
Kling OmniVideo API: JWT auth, request types, create/poll/download in one module.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import jwt
import requests


@dataclass(frozen=True)
class _KlingJwtConfig:
    access_key: str
    secret_key: str
    ttl_seconds: int = 1800
    nbf_skew_seconds: int = 5


def _kling_bearer_token(cfg: _KlingJwtConfig) -> str:
    now = int(time.time())
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {"iss": cfg.access_key, "exp": now + cfg.ttl_seconds, "nbf": now - cfg.nbf_skew_seconds}
    token = jwt.encode(payload, cfg.secret_key, algorithm="HS256", headers=headers)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


@dataclass(frozen=True)
class KlingGenerateRequest:
    model_name: str = "kling-v3-omni"
    mode: str = "pro"
    aspect_ratio: str = "16:9"
    duration: str = "5"
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    image_list: Optional[list[dict[str, Any]]] = None
    video_list: Optional[list[dict[str, Any]]] = None
    element_list: Optional[list[str]] = None
    watermark: Optional[dict[str, Any]] = None
    callback_url: Optional[str] = None
    external_task_id: Optional[str] = None
    multi_shot: Optional[bool] = None
    shot_type: Optional[str] = None
    multi_prompt: Optional[list[dict[str, Any]]] = None

    @staticmethod
    def from_scene_dict(scene: dict[str, Any]) -> "KlingGenerateRequest":
        return KlingGenerateRequest(
            model_name=str(scene.get("model_name") or "kling-v3-omni"),
            mode=str(scene.get("mode") or "pro"),
            aspect_ratio=str(scene.get("aspect_ratio") or "16:9"),
            duration=str(scene.get("duration") or "5"),
            prompt=scene.get("prompt"),
            negative_prompt=scene.get("negative_prompt"),
            image_list=scene.get("image_list"),
            video_list=scene.get("video_list"),
            element_list=scene.get("element_list"),
            watermark=scene.get("watermark") or {"enabled": False},
            callback_url=scene.get("callback_url"),
            external_task_id=scene.get("external_task_id"),
            multi_shot=scene.get("multi_shot"),
            shot_type=scene.get("shot_type"),
            multi_prompt=scene.get("multi_prompt"),
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model_name": self.model_name,
            "mode": self.mode,
            "aspect_ratio": self.aspect_ratio,
            "duration": self.duration,
        }
        if self.watermark is not None:
            payload["watermark"] = self.watermark
        if self.prompt is not None:
            payload["prompt"] = self.prompt
        if self.negative_prompt:
            payload["negative_prompt"] = self.negative_prompt
        if self.image_list:
            payload["image_list"] = self.image_list
        if self.video_list:
            payload["video_list"] = self.video_list
        if self.element_list:
            payload["element_list"] = self.element_list
        if self.callback_url:
            payload["callback_url"] = self.callback_url
        if self.external_task_id:
            payload["external_task_id"] = self.external_task_id
        if self.multi_shot:
            payload["multi_shot"] = True
            if self.shot_type:
                payload["shot_type"] = self.shot_type
            if self.multi_prompt:
                payload["multi_prompt"] = self.multi_prompt
        return payload


@dataclass
class KlingTaskResult:
    raw: dict[str, Any]

    @property
    def raw_json(self) -> str:
        return json.dumps(self.raw, indent=2, ensure_ascii=False)

    def best_video_url(self) -> Optional[str]:
        data = self.raw.get("data") or {}
        task_result = data.get("task_result") or {}
        videos = task_result.get("videos") or []
        if not videos:
            return None
        first = videos[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for k in ("url", "video_url", "download_url"):
                v = first.get(k)
                if isinstance(v, str) and v:
                    return v
        return None


class KlingClient:
    """OmniVideo: JWT auth, create task, poll, download."""

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        api_base: str = "https://api-singapore.klingai.com",
    ):
        self._jwt_cfg = _KlingJwtConfig(access_key=access_key, secret_key=secret_key)
        self.api_base = api_base.rstrip("/")

    def _headers(self) -> dict[str, str]:
        token = _kling_bearer_token(self._jwt_cfg)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def create_omni_video_task(self, req: KlingGenerateRequest) -> str:
        url = f"{self.api_base}/v1/videos/omni-video"
        resp = requests.post(url, headers=self._headers(), json=req.to_payload(), timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") not in (0, "0", None):
            raise RuntimeError(
                f"Kling error: {data.get('code')} {data.get('message')}\n{json.dumps(data, indent=2)}"
            )
        task_id = (data.get("data") or {}).get("task_id")
        if not task_id:
            raise RuntimeError("No task_id returned.\n" + json.dumps(data, indent=2))
        return str(task_id)

    def get_task(self, task_id: str) -> KlingTaskResult:
        url = f"{self.api_base}/v1/videos/omni-video/{task_id}"
        resp = requests.get(url, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        return KlingTaskResult(resp.json())

    def wait_for_task(
        self,
        task_id: str,
        timeout_seconds: int = 600,
        poll_every_seconds: int = 3,
    ) -> KlingTaskResult:
        start = time.time()
        last: Optional[KlingTaskResult] = None
        while True:
            last = self.get_task(task_id)
            status = ((last.raw.get("data") or {}).get("task_status") or "").lower()
            if status in {"succeed", "success", "completed", "done"}:
                return last
            if status in {"failed", "error", "canceled", "cancelled"}:
                raise RuntimeError("Kling task failed.\n" + last.raw_json)
            if time.time() - start > timeout_seconds:
                raise TimeoutError(
                    "Timed out waiting for Kling task.\nLast response:\n"
                    + (last.raw_json if last else "None")
                )
            time.sleep(poll_every_seconds)

    def download_video(self, url: str, out_path: Path) -> None:
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            out_path.write_bytes(r.content)
