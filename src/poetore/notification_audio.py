"""Audio storage and playback for hideout-stay notifications."""

from __future__ import annotations

import shutil
import sys
import threading
import time
from array import array
from enum import StrEnum
from importlib import import_module
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from src.poetore.hideout_notification import (
    BUNDLED_SOUND_OPTIONS,
    DEFAULT_BUNDLED_SOUND_ID,
)
from src.utils.config_manager import ConfigManager
from src.utils.state_machine import StateMachine

CUSTOM_AUDIO_STEM = "poetore-hideout-notification"
SUPPORTED_AUDIO_SUFFIXES = {".wav", ".mp3"}
_BUNDLED_SOUND_FILES = {
    sound_id: filename for sound_id, _label, filename in BUNDLED_SOUND_OPTIONS
}


def verify_audio_runtime():
    """Import the packaged backend and decode every bundled sound."""
    import_module("_cffi_backend")
    first_decoded = None
    for sound_id, label, _filename in BUNDLED_SOUND_OPTIONS:
        decoded = _decode_audio_file(bundled_audio_path(sound_id))
        if decoded.num_frames <= 0 or decoded.duration <= 0:
            raise RuntimeError(f"{label}をデコードできませんでした")
        if first_decoded is None:
            first_decoded = decoded
    return first_decoded


def bundled_audio_path(sound_id: str = DEFAULT_BUNDLED_SOUND_ID) -> Path:
    filename = _BUNDLED_SOUND_FILES.get(
        str(sound_id), _BUNDLED_SOUND_FILES[DEFAULT_BUNDLED_SOUND_ID]
    )
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))
        roots.append(Path(sys.executable).parent)
    roots.append(Path(__file__).resolve().parents[2])
    for root in roots:
        candidate = root / "assets" / "audio" / filename
        if candidate.is_file():
            return candidate
    return roots[0] / "assets" / "audio" / filename


def custom_audio_path(filename: str) -> Path:
    safe_name = Path(str(filename or "")).name
    if not safe_name:
        return ConfigManager.get_user_data_dir() / f"{CUSTOM_AUDIO_STEM}.wav"
    return ConfigManager.get_user_data_dir() / safe_name


def _decode_audio_file(path: str | Path, **decode_options):
    """Decode audio without passing a filesystem path to miniaudio.

    miniaudio's filename API uses a narrow C string on Windows and cannot
    reliably open paths containing Japanese characters.  Python's file API
    is Unicode-aware, so read the encoded file first and decode it in memory.
    """
    import miniaudio

    return miniaudio.decode(Path(path).read_bytes(), **decode_options)


def copy_custom_audio(source: str | Path) -> tuple[str, str]:
    source_path = Path(source)
    suffix = source_path.suffix.casefold()
    if suffix not in SUPPORTED_AUDIO_SUFFIXES:
        raise ValueError("WAVまたはMP3ファイルを選択してください。")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    # Reject corrupt or mislabeled files while the settings dialog can still
    # explain the problem. Playback keeps its own fallback for files that
    # become unreadable after they have been selected.
    try:
        import miniaudio
    except ImportError as error:
        raise ValueError(
            "通知音の再生機能を読み込めませんでした。アプリを再起動してください。"
        ) from error

    try:
        _decode_audio_file(source_path)
    except miniaudio.MiniaudioError as error:
        raise ValueError(
            "通知音ファイルを読み込めませんでした。別のWAVまたはMP3を選択してください。"
        ) from error
    destination = ConfigManager.get_user_data_dir() / f"{CUSTOM_AUDIO_STEM}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source_path, temporary)
    temporary.replace(destination)
    for obsolete_suffix in SUPPORTED_AUDIO_SUFFIXES - {suffix}:
        destination.with_suffix(obsolete_suffix).unlink(missing_ok=True)
    return source_path.name, destination.name


def scale_signed16(samples, volume: int) -> array:
    """Scale PCM with a soft limiter. 50 means original amplitude."""
    pcm = array("h", samples)
    volume = max(0, min(100, int(volume)))
    if volume == 50:
        return pcm
    if volume == 0:
        return array("h", [0]) * len(pcm)
    gain = volume / 50.0
    if gain < 1.0:
        return array("h", (round(sample * gain) for sample in pcm))

    # Quiet samples approach the requested gain (up to 2x), while peaks are
    # smoothly compressed instead of being hard-clipped.
    scaled = array("h")
    for sample in pcm:
        normalized = sample / 32768.0
        limited = (gain * normalized) / (
            1.0 + ((gain - 1.0) * abs(normalized))
        )
        scaled.append(max(-32768, min(32767, round(limited * 32768.0))))
    return scaled


class AudioPlaybackState(StrEnum):
    IDLE = "idle"
    PLAYING = "playing"
    STOPPING = "stopping"


AUDIO_PLAYBACK_TRANSITIONS = {
    AudioPlaybackState.IDLE: frozenset({AudioPlaybackState.PLAYING}),
    AudioPlaybackState.PLAYING: frozenset({
        AudioPlaybackState.IDLE, AudioPlaybackState.STOPPING,
    }),
    AudioPlaybackState.STOPPING: frozenset({AudioPlaybackState.IDLE}),
}


class NotificationAudioPlayer(QObject):
    fallback_used = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._sm = StateMachine(
            "notification audio", AudioPlaybackState.IDLE, AUDIO_PLAYBACK_TRANSITIONS,
        )
        self._stop_event = threading.Event()

    @property
    def state(self) -> AudioPlaybackState:
        with self._lock:
            return self._sm.state

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._sm.is_in(AudioPlaybackState.PLAYING, AudioPlaybackState.STOPPING)

    @property
    def _playing(self) -> bool:
        return self.is_playing

    @_playing.setter
    def _playing(self, playing: bool) -> None:
        # Keep direct worker test setup compatible without storing a second state.
        with self._lock:
            if playing and self._sm.state is AudioPlaybackState.IDLE:
                self._sm.transition(AudioPlaybackState.PLAYING)
            elif not playing:
                self._sm.transition(AudioPlaybackState.IDLE, allow_same=True)

    def play(self, primary: Path, fallback: Path, volume: int) -> bool:
        with self._lock:
            if self._sm.state is not AudioPlaybackState.IDLE:
                return False
            self._stop_event.clear()
            self._sm.transition(AudioPlaybackState.PLAYING)
        try:
            threading.Thread(
                target=self._play_worker,
                args=(Path(primary), Path(fallback), int(volume)),
                daemon=True,
                name="PoEToreNotificationAudio",
            ).start()
        except Exception:
            with self._lock:
                self._sm.transition(AudioPlaybackState.IDLE)
            raise
        return True

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            if self._sm.state is AudioPlaybackState.PLAYING:
                self._sm.transition(AudioPlaybackState.STOPPING)

    def _play_worker(self, primary: Path, fallback: Path, volume: int) -> None:
        try:
            try:
                self._play_file(primary, volume)
            except Exception:  # miniaudio exposes multiple decoder/device errors
                if primary == fallback:
                    raise
                self.fallback_used.emit(
                    "設定した音を再生できなかったため、標準音1を使用しました"
                )
                self._play_file(fallback, volume)
        except Exception as error:  # keep audio/backend failures outside the UI thread
            self.failed.emit(f"通知音を再生できませんでした: {error}")
        finally:
            with self._lock:
                self._sm.transition(AudioPlaybackState.IDLE, allow_same=True)
            self.finished.emit()

    def _play_file(self, path: Path, volume: int) -> None:
        import miniaudio

        if not path.is_file():
            raise FileNotFoundError(path)
        decoded = _decode_audio_file(
            path,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=2,
            sample_rate=44100,
        )
        samples = scale_signed16(decoded.samples, volume)
        stream = miniaudio.stream_raw_pcm_memory(samples, 2, 2)
        with miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=2,
            sample_rate=44100,
        ) as device:
            device.start(stream)
            deadline = time.monotonic() + float(decoded.duration) + 0.15
            while time.monotonic() < deadline and not self._stop_event.wait(0.02):
                pass
            device.stop()
