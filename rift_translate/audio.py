from __future__ import annotations

import tempfile
import threading
import wave
from pathlib import Path
from uuid import uuid4

import numpy as np
import sounddevice as sd


class AudioRecorder:
    def __init__(self, sample_rate: int = 16_000) -> None:
        self.sample_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self._frames = []
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=self._on_audio,
            )
            self._stream.start()

    def _on_audio(
        self,
        indata: np.ndarray,
        _frames: int,
        _time: object,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            # Audio status is intentionally not printed during gameplay.
            pass
        self._frames.append(indata.copy())

    def stop(self) -> Path:
        with self._lock:
            if self._stream is None:
                raise RuntimeError("当前没有正在录制的语音。")
            stream = self._stream
            self._stream = None

        stream.stop()
        stream.close()

        if not self._frames:
            raise RuntimeError("没有录到声音，请检查麦克风权限。")

        audio = np.concatenate(self._frames, axis=0).reshape(-1)
        duration = len(audio) / self.sample_rate
        if duration < 0.25:
            raise RuntimeError("录音太短，请按住 F8 说完后再松开。")

        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype(np.int16)

        output = Path(tempfile.gettempdir()) / f"rift-translate-{uuid4().hex}.wav"
        with wave.open(str(output), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm.tobytes())
        return output

    def cancel(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            stream.stop()
            stream.close()
        self._frames = []
