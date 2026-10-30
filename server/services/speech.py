"""Local speech recognition for the workbench composer."""

from __future__ import annotations

import io
import logging
import os
import threading
from pathlib import Path
from typing import Any


MODEL_NAME = "faster-whisper-small"
MAX_AUDIO_SECONDS = 60
MAX_AUDIO_BYTES = 12 * 1024 * 1024
_MODEL_LOCK = threading.Lock()
_MODEL: Any | None = None
_LOGGER = logging.getLogger(__name__)


class SpeechModelUnavailable(RuntimeError):
    """Raised when the optional local ASR runtime is not installed."""


class InvalidAudio(ValueError):
    """Raised when audio cannot be decoded or is longer than the limit."""


class SpeechRecognitionError(RuntimeError):
    """Raised when the local recognition runtime fails after loading."""


def _model_cache_dir() -> Path:
    configured = os.environ.get("QUALITY_ASR_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".cache"
    return base / "QualityAgent" / "models"


def _local_model_path() -> Path | None:
    configured = os.environ.get("QUALITY_ASR_MODEL_PATH")
    if configured:
        path = Path(configured).expanduser()
        return path if (path / "model.bin").is_file() and (path / "config.json").is_file() else None
    snapshots = _model_cache_dir() / "models--Systran--faster-whisper-small" / "snapshots"
    if snapshots.is_dir():
        for snapshot in snapshots.iterdir():
            if (snapshot / "model.bin").is_file() and (snapshot / "config.json").is_file():
                return snapshot
    return None


def speech_status() -> dict[str, str]:
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except Exception:
        return {
            "status": "dependency_missing",
            "model_name": MODEL_NAME,
            "message": "本地语音组件尚未安装。请运行 start_app.bat 或在项目虚拟环境安装 requirements-speech.txt。",
        }
    if _local_model_path() is not None:
        return {"status": "ready", "model_name": MODEL_NAME, "message": "本地模型已就绪，使用 CPU INT8 识别。"}
    return {
        "status": "model_missing",
        "model_name": MODEL_NAME,
        "message": "本地模型尚未下载。首次识别需要联网下载约 500 MB 的中文语音模型。",
    }


def _get_model() -> Any:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise SpeechModelUnavailable("本地语音组件尚未安装，请安装 requirements-speech.txt 后重启服务。") from error
        local_path = _local_model_path()
        _MODEL = WhisperModel(
            str(local_path) if local_path else "small",
            device="cpu",
            compute_type="int8",
            cpu_threads=max(1, min(4, (os.cpu_count() or 4) - 1)),
            num_workers=1,
            download_root=str(_model_cache_dir()),
        )
        return _MODEL


def _decode_audio(audio: bytes) -> tuple[Any, float]:
    try:
        import av
        import numpy as np

        with av.open(io.BytesIO(audio)) as container:
            stream = next((item for item in container.streams if item.type == "audio"), None)
            if stream is None:
                raise InvalidAudio("没有在录音文件中找到音轨。")
            duration = container.duration
            if duration is None and stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base * av.time_base)
            elif duration is not None:
                duration = float(duration)
            if duration is not None and duration / av.time_base > MAX_AUDIO_SECONDS:
                raise InvalidAudio("单次语音最多录制 60 秒，请分段提问。")

            resampler = av.AudioResampler(format="flt", layout="mono", rate=16_000)
            chunks = []
            sample_count = 0

            def collect(frames: list[Any]) -> None:
                nonlocal sample_count
                for frame in frames:
                    samples = frame.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                    sample_count += samples.size
                    if sample_count > MAX_AUDIO_SECONDS * 16_000:
                        raise InvalidAudio("单次语音最多录制 60 秒，请分段提问。")
                    chunks.append(samples)

            for frame in container.decode(stream):
                collect(resampler.resample(frame))
            collect(resampler.resample(None))
            if not chunks:
                raise InvalidAudio("没有在录音文件中找到有效音频。")
            waveform = np.concatenate(chunks)
            return waveform, sample_count / 16_000
    except InvalidAudio:
        raise
    except ImportError as error:
        raise SpeechModelUnavailable("本地语音依赖尚未安装，请安装 requirements-speech.txt 后重启服务。") from error
    except Exception as error:
        _LOGGER.warning(
            "Could not decode uploaded speech audio (%d bytes; %s)",
            len(audio),
            type(error).__name__,
            exc_info=True,
        )
        raise InvalidAudio("录音格式无法读取，请重新录音后重试。") from error
    return 0.0


def transcribe_audio(audio: bytes) -> dict[str, str | float]:
    waveform, duration = _decode_audio(audio)
    if duration > MAX_AUDIO_SECONDS:
        raise InvalidAudio("单次语音最多录制 60 秒，请分段提问。")
    try:
        model = _get_model()
    except SpeechModelUnavailable:
        raise
    except Exception as error:
        raise SpeechModelUnavailable("本地语音模型加载或下载失败。请检查网络后重试；模型文件会保存在本机。") from error
    try:
        segments, info = model.transcribe(
            waveform,
            language="zh",
            beam_size=5,
            vad_filter=True,
            initial_prompt="制造质量分析术语：质量、不良率、缺陷、产线、工位、批次、班次、车型、扭矩、压力、温度、CPK、SPC。请准确保留字母和数字编号。",
        )
        text = "".join(segment.text for segment in segments).strip()
        actual_duration = float(info.duration or duration)
    except Exception as error:
        raise SpeechRecognitionError("本地语音识别运行失败，请重新录音后重试。") from error
    if not text:
        raise InvalidAudio("没有识别到清晰语音，请靠近麦克风后重试。")
    if actual_duration > MAX_AUDIO_SECONDS:
        raise InvalidAudio("单次语音最多录制 60 秒，请分段提问。")
    return {"text": text, "language": str(info.language or "zh"), "duration_seconds": round(actual_duration, 2)}
