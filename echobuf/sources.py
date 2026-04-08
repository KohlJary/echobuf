"""Per-app audio capture via PulseAudio null sink routing.

Creates a null sink, moves the target app's sink-input to it, adds a
loopback so the user still hears audio, and records from the null
sink's monitor. Restores original routing on cleanup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pulsectl

log = logging.getLogger(__name__)

CAPTURE_SINK_NAME = "echobuf_capture"


@dataclass
class SourceInfo:
    """Describes an available capture source."""
    type: str           # "system" or "app"
    name: str           # display name
    app_binary: str = ""  # binary name for app sources
    sink_input_id: int = -1


class PerAppCapture:
    """Manages PulseAudio routing for per-app capture.

    Creates a null sink, moves the target sink-input to it, and adds
    a loopback back to the original sink so the user keeps hearing audio.
    """

    def __init__(self) -> None:
        self._pulse: pulsectl.Pulse | None = None
        self._null_sink_module: int | None = None
        self._loopback_module: int | None = None
        self._original_sink: str | None = None
        self._captured_sink_input: int | None = None

    def list_sources(self) -> list[SourceInfo]:
        """List available capture sources (system + running apps)."""
        sources = [SourceInfo(type="system", name="System audio (default monitor)")]

        try:
            with pulsectl.Pulse("echobuf-list") as pulse:
                for si in pulse.sink_input_list():
                    props = si.proplist
                    app_name = props.get("application.name", "unknown")
                    app_binary = props.get("application.process.binary", "")
                    sources.append(SourceInfo(
                        type="app",
                        name=app_name,
                        app_binary=app_binary,
                        sink_input_id=si.index,
                    ))
        except pulsectl.PulseError:
            log.warning("Could not enumerate PulseAudio sink inputs", exc_info=True)

        return sources

    def setup(self, target: str) -> str:
        """Set up per-app capture for the given app name or binary.

        Returns the monitor source name to record from.
        """
        self._pulse = pulsectl.Pulse("echobuf-capture")

        # Find the target sink-input
        sink_input = self._find_sink_input(target)
        if sink_input is None:
            raise RuntimeError(f"No audio stream found for '{target}'")

        self._captured_sink_input = sink_input.index

        # Remember original sink for restoration
        self._original_sink = self._get_default_sink_name()

        # Load null sink
        self._null_sink_module = self._pulse.module_load(
            "module-null-sink",
            f"sink_name={CAPTURE_SINK_NAME} "
            f'sink_properties=device.description="echobuf_capture"',
        )
        log.info("Loaded null sink (module %d)", self._null_sink_module)

        # Move the target sink-input to our null sink
        self._pulse.sink_input_move(sink_input.index, self._get_sink_index(CAPTURE_SINK_NAME))
        log.info("Moved sink-input %d (%s) to %s", sink_input.index, target, CAPTURE_SINK_NAME)

        # Add loopback from null sink back to original sink so user still hears audio
        if self._original_sink:
            self._loopback_module = self._pulse.module_load(
                "module-loopback",
                f"source={CAPTURE_SINK_NAME}.monitor "
                f"sink={self._original_sink} "
                "latency_msec=30",
            )
            log.info("Loaded loopback to %s (module %d)", self._original_sink, self._loopback_module)

        return f"{CAPTURE_SINK_NAME}.monitor"

    def teardown(self) -> None:
        """Restore original routing and clean up modules."""
        if self._pulse is None:
            return

        try:
            # Restore sink-input to original sink
            if self._captured_sink_input is not None and self._original_sink:
                try:
                    original_idx = self._get_sink_index(self._original_sink)
                    self._pulse.sink_input_move(self._captured_sink_input, original_idx)
                    log.info("Restored sink-input %d to %s", self._captured_sink_input, self._original_sink)
                except pulsectl.PulseError:
                    log.warning("Could not restore sink-input routing (stream may have ended)")

            # Unload loopback
            if self._loopback_module is not None:
                try:
                    self._pulse.module_unload(self._loopback_module)
                    log.info("Unloaded loopback module %d", self._loopback_module)
                except pulsectl.PulseError:
                    pass
                self._loopback_module = None

            # Unload null sink
            if self._null_sink_module is not None:
                try:
                    self._pulse.module_unload(self._null_sink_module)
                    log.info("Unloaded null sink module %d", self._null_sink_module)
                except pulsectl.PulseError:
                    pass
                self._null_sink_module = None

        finally:
            self._pulse.close()
            self._pulse = None
            self._captured_sink_input = None
            self._original_sink = None

    def _find_sink_input(self, target: str) -> pulsectl.PulseSinkInputInfo | None:
        """Find a sink-input matching the target name (app name or binary)."""
        assert self._pulse is not None
        target_lower = target.lower()
        for si in self._pulse.sink_input_list():
            props = si.proplist
            app_name = props.get("application.name", "").lower()
            app_binary = props.get("application.process.binary", "").lower()
            if target_lower in (app_name, app_binary) or target_lower in app_name:
                return si
        return None

    def _get_default_sink_name(self) -> str | None:
        """Get the name of the current default sink."""
        assert self._pulse is not None
        info = self._pulse.server_info()
        return info.default_sink_name

    def _get_sink_index(self, sink_name: str) -> int:
        """Get the index of a sink by name."""
        assert self._pulse is not None
        for sink in self._pulse.sink_list():
            if sink.name == sink_name:
                return sink.index
        raise RuntimeError(f"Sink '{sink_name}' not found")
