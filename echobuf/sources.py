"""Per-app audio capture routing for PulseAudio and PipeWire.

PulseAudio: null sink + loopback approach (user hears via loopback, ~30ms latency).
PipeWire: virtual sink + graph linking (user hears natively, no latency penalty).
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass

import pulsectl

log = logging.getLogger(__name__)

CAPTURE_SINK_NAME = "echobuf_capture"


@dataclass
class SourceInfo:
    """Describes an available capture source."""
    type: str           # "system" or "app"
    name: str           # display name
    app_binary: str = ""
    sink_input_id: int = -1
    pw_node_id: int = -1


def list_sources() -> list[SourceInfo]:
    """List available capture sources (system + running apps).

    Works on both PulseAudio and PipeWire (via pipewire-pulse).
    """
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


# ---------------------------------------------------------------------------
# PulseAudio per-app capture
# ---------------------------------------------------------------------------

class PulsePerAppCapture:
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

    def setup(self, target: str) -> str:
        """Set up per-app capture. Returns the monitor source name to record from."""
        self._pulse = pulsectl.Pulse("echobuf-capture")

        sink_input = self._find_sink_input(target)
        if sink_input is None:
            raise RuntimeError(f"No audio stream found for '{target}'")

        self._captured_sink_input = sink_input.index
        self._original_sink = self._get_default_sink_name()

        self._null_sink_module = self._pulse.module_load(
            "module-null-sink",
            f"sink_name={CAPTURE_SINK_NAME} "
            f'sink_properties=device.description="echobuf_capture"',
        )
        log.info("Loaded null sink (module %d)", self._null_sink_module)

        self._pulse.sink_input_move(sink_input.index, self._get_sink_index(CAPTURE_SINK_NAME))
        log.info("Moved sink-input %d (%s) to %s", sink_input.index, target, CAPTURE_SINK_NAME)

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
        if self._pulse is None:
            return

        try:
            if self._captured_sink_input is not None and self._original_sink:
                try:
                    original_idx = self._get_sink_index(self._original_sink)
                    self._pulse.sink_input_move(self._captured_sink_input, original_idx)
                    log.info("Restored sink-input %d to %s", self._captured_sink_input, self._original_sink)
                except pulsectl.PulseError:
                    log.warning("Could not restore sink-input routing (stream may have ended)")

            if self._loopback_module is not None:
                try:
                    self._pulse.module_unload(self._loopback_module)
                except pulsectl.PulseError:
                    pass
                self._loopback_module = None

            if self._null_sink_module is not None:
                try:
                    self._pulse.module_unload(self._null_sink_module)
                except pulsectl.PulseError:
                    pass
                self._null_sink_module = None
        finally:
            self._pulse.close()
            self._pulse = None
            self._captured_sink_input = None
            self._original_sink = None

    def _find_sink_input(self, target: str) -> pulsectl.PulseSinkInputInfo | None:
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
        assert self._pulse is not None
        return self._pulse.server_info().default_sink_name

    def _get_sink_index(self, sink_name: str) -> int:
        assert self._pulse is not None
        for sink in self._pulse.sink_list():
            if sink.name == sink_name:
                return sink.index
        raise RuntimeError(f"Sink '{sink_name}' not found")


# Backward compat alias
PerAppCapture = PulsePerAppCapture


# ---------------------------------------------------------------------------
# PipeWire per-app capture via graph linking
# ---------------------------------------------------------------------------

class PipeWirePerAppCapture:
    """Per-app capture using PipeWire's native graph model.

    Creates a virtual sink node, then links the target app's output ports
    to both the original sink AND our capture node. The user keeps hearing
    audio at full quality with no loopback latency.
    """

    def __init__(self) -> None:
        self._virtual_node_id: int | None = None
        self._created_links: list[int] = []

    def setup(self, target: str) -> str:
        """Set up per-app capture. Returns the node name to use as --target for pw-record."""
        # Find the target app's node
        target_node = self._find_app_node(target)
        if target_node is None:
            raise RuntimeError(f"No PipeWire node found for '{target}'")

        target_name = target_node.get("node.name", target)

        # Create a virtual sink for capture
        result = subprocess.run(
            [
                "pw-cli", "create-node", "adapter",
                f"{{ factory.name=support.null-audio-sink "
                f"node.name={CAPTURE_SINK_NAME} "
                f'node.description="echobuf capture" '
                f"media.class=Audio/Sink "
                f"audio.position=[FL FR] "
                f"monitor.channel-volumes=true }}",
            ],
            capture_output=True, text=True,
        )
        # Parse the node id from output
        self._virtual_node_id = self._parse_node_id(result.stdout)
        if self._virtual_node_id is None:
            raise RuntimeError(f"Failed to create virtual sink: {result.stderr}")
        log.info("Created PipeWire virtual sink node %d", self._virtual_node_id)

        # Find the app's output ports and the virtual sink's input ports
        app_out_ports = self._get_output_ports(target_name)
        capture_in_ports = self._get_input_ports(CAPTURE_SINK_NAME)

        if not app_out_ports or not capture_in_ports:
            log.warning("Could not find ports to link (app=%d, capture=%d)",
                        len(app_out_ports), len(capture_in_ports))
            # Still return — pw-record --target can handle it
        else:
            # Link app outputs to our capture sink inputs
            for out_port, in_port in zip(app_out_ports, capture_in_ports):
                self._link_ports(out_port, in_port)

        return CAPTURE_SINK_NAME

    def teardown(self) -> None:
        # Destroy links we created
        for link_id in self._created_links:
            try:
                subprocess.run(["pw-cli", "destroy", str(link_id)],
                              capture_output=True, timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass
        self._created_links.clear()

        # Destroy our virtual sink
        if self._virtual_node_id is not None:
            try:
                subprocess.run(["pw-cli", "destroy", str(self._virtual_node_id)],
                              capture_output=True, timeout=5)
                log.info("Destroyed PipeWire virtual sink node %d", self._virtual_node_id)
            except (subprocess.TimeoutExpired, OSError):
                pass
            self._virtual_node_id = None

    def _find_app_node(self, target: str) -> dict | None:
        """Find a PipeWire node matching the target app name."""
        try:
            result = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5)
            nodes = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            return None

        target_lower = target.lower()
        for obj in nodes:
            if obj.get("type") != "PipeWire:Interface:Node":
                continue
            props = obj.get("info", {}).get("props", {})
            node_name = props.get("node.name", "").lower()
            app_name = props.get("application.name", "").lower()
            media_class = props.get("media.class", "")

            # Only match playback streams
            if "Stream/Output" not in media_class:
                continue

            if target_lower in node_name or target_lower in app_name:
                return props
        return None

    def _get_output_ports(self, node_name: str) -> list[str]:
        """Get output port names for a node."""
        try:
            result = subprocess.run(["pw-link", "-o"], capture_output=True, text=True, timeout=5)
            return [line.strip() for line in result.stdout.splitlines()
                    if line.strip().startswith(f"{node_name}:output_")]
        except (subprocess.TimeoutExpired, OSError):
            return []

    def _get_input_ports(self, node_name: str) -> list[str]:
        """Get input port names for a node."""
        try:
            result = subprocess.run(["pw-link", "-i"], capture_output=True, text=True, timeout=5)
            return [line.strip() for line in result.stdout.splitlines()
                    if line.strip().startswith(f"{node_name}:playback_")]
        except (subprocess.TimeoutExpired, OSError):
            return []

    def _link_ports(self, output: str, input: str) -> None:
        """Create a link between two ports."""
        try:
            result = subprocess.run(
                ["pw-link", output, input],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                # Try to find the link id for cleanup
                link_id = self._find_link_id(output, input)
                if link_id is not None:
                    self._created_links.append(link_id)
                log.info("Linked %s -> %s", output, input)
            else:
                log.warning("Failed to link %s -> %s: %s", output, input, result.stderr.strip())
        except (subprocess.TimeoutExpired, OSError):
            log.warning("Timeout linking %s -> %s", output, input)

    def _find_link_id(self, output: str, input: str) -> int | None:
        """Find the PipeWire object id for a link."""
        try:
            result = subprocess.run(["pw-link", "-l", "-I"], capture_output=True, text=True, timeout=5)
            # pw-link -l -I shows link IDs; parse output
            for line in result.stdout.splitlines():
                if output in line and input in line:
                    parts = line.strip().split()
                    for part in parts:
                        if part.isdigit():
                            return int(part)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None

    def _parse_node_id(self, output: str) -> int | None:
        """Parse node id from pw-cli create-node output."""
        # Output format: "id: <N>, ..."
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("id:"):
                try:
                    return int(line.split(",")[0].split(":")[1].strip())
                except (IndexError, ValueError):
                    pass
        return None
