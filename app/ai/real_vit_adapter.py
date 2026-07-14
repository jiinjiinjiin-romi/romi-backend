from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Any

from app.ai.driver_monitoring import DetectionResult, InferenceFrame
from app.ai.prediction_mapper import metadata_from_class_index
from app.core.config import Settings
from app.core.time import utc_now_for_api_response

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class RealViTAdapter:
    def __init__(self, settings: Settings) -> None:
        self._model_path = Path(settings.model_path)
        self._model_version = settings.model_version
        self._device_name = settings.model_device
        self._input_size = settings.model_input_size
        self._torch_num_threads = settings.torch_num_threads
        self._loaded: dict[str, Any] | None = None
        self._load_lock = asyncio.Lock()

    @property
    def model_version(self) -> str:
        return self._model_version

    async def is_ready(self) -> bool:
        return self._model_path.expanduser().exists()

    async def aclose(self) -> None:
        self._loaded = None

    async def predict(self, frame: InferenceFrame) -> DetectionResult:
        result = await self.predict_scores(frame.jpeg_bytes)
        top_index = max(range(len(result.scores)), key=result.scores.__getitem__)
        metadata = metadata_from_class_index(top_index)
        started_at = result.started_at
        completed_at = result.completed_at

        return DetectionResult(
            session_id=frame.session_id,
            frame_id=frame.frame_id,
            model_action_type=metadata.action_type,
            model_class_code=metadata.class_code,
            model_class_label=metadata.class_label,
            behavior_type=metadata.detection_behavior_type,
            confidence=round(float(result.scores[top_index]), 4),
            model_version=self.model_version,
            captured_at=frame.captured_at,
            inference_started_at=started_at,
            inference_completed_at=completed_at,
            inference_latency_ms=max(0, int((completed_at - started_at).total_seconds() * 1000)),
        )

    async def predict_scores(self, jpeg_bytes: bytes) -> RealViTPrediction:
        torch = self._import_torch()
        started_at = utc_now_for_api_response()
        started = perf_counter()
        loaded = await self._load()
        tensor = self._image_bytes_to_tensor(jpeg_bytes, torch, loaded["device"])

        with torch.inference_mode():
            logits = loaded["model"](tensor)
            scores = torch.softmax(logits, dim=1).squeeze(0).detach().cpu().tolist()

        completed_at = utc_now_for_api_response()
        elapsed_ms = (perf_counter() - started) * 1000
        return RealViTPrediction(
            scores=[round(float(score), 4) for score in scores],
            started_at=started_at,
            completed_at=completed_at,
            elapsed_ms=elapsed_ms,
        )

    async def _load(self) -> dict[str, Any]:
        if self._loaded is not None:
            return self._loaded

        async with self._load_lock:
            if self._loaded is not None:
                return self._loaded

            torch = self._import_torch()
            if self._torch_num_threads > 0:
                torch.set_num_threads(self._torch_num_threads)
            try:
                import timm
            except ImportError as exc:
                raise RuntimeError("The timm package is required for REAL ViT inference.") from exc

            device = self._resolve_device(torch)
            model = _create_backbone_wrapper(
                torch,
                timm.create_model("vit_base_patch16_224", pretrained=False, num_classes=5),
            )
            checkpoint = torch.load(
                self._model_path.expanduser().resolve(),
                map_location="cpu",
                weights_only=False,
            )
            model.load_state_dict(_extract_state_dict(checkpoint), strict=True)
            model.to(device)
            model.eval()
            self._loaded = {"device": device, "model": model}
            return self._loaded

    def _image_bytes_to_tensor(self, frame: bytes, torch: Any, device: Any) -> Any:
        from PIL import Image

        image = Image.open(BytesIO(frame)).convert("RGB").resize(
            (self._input_size, self._input_size)
        )
        data = torch.frombuffer(bytearray(image.tobytes()), dtype=torch.uint8)
        tensor = (
            data.view(self._input_size, self._input_size, 3)
            .permute(2, 0, 1)
            .float()
            .div(255.0)
        )
        mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
        std = torch.tensor(IMAGENET_STD).view(3, 1, 1)
        return ((tensor - mean) / std).unsqueeze(0).to(device)

    def _resolve_device(self, torch: Any) -> Any:
        if self._device_name == "cuda" and torch.cuda.is_available():
            return torch.device("cuda")
        if self._device_name == "mps" and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")

    @staticmethod
    def _import_torch() -> Any:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("The torch package is required for REAL ViT inference.") from exc
        return torch


class RealViTPrediction:
    def __init__(
        self,
        *,
        scores: list[float],
        started_at,
        completed_at,
        elapsed_ms: float,
    ) -> None:
        self.scores = scores
        self.started_at = started_at
        self.completed_at = completed_at
        self.elapsed_ms = elapsed_ms


def _extract_state_dict(checkpoint: Any) -> dict[str, Any]:
    if not isinstance(checkpoint, dict):
        raise ValueError("Checkpoint must be a state_dict or dictionary.")
    for key in ("model_state_dict", "state_dict", "model", "net"):
        value = checkpoint.get(key)
        if isinstance(value, dict):
            return value
    if checkpoint and all(isinstance(key, str) for key in checkpoint):
        return checkpoint
    raise ValueError("Checkpoint does not include a valid state_dict.")


def _create_backbone_wrapper(torch: Any, backbone: Any) -> Any:
    class BackboneWrapper(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.backbone = backbone

        def forward(self, image: Any) -> Any:
            return self.backbone(image)

    return BackboneWrapper()
