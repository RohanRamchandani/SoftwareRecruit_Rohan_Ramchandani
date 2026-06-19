import sys
import time

# GStreamer doesn't speak Python on its own -- the `gi` bindings ("PyGObject") are the bridge that lets Python call into it. We have to declare which GStreamer version we want BEFORE importing it, hence the require_version line.
import gi
gi.require_version("Gst", "1.0") # ask for the GStreamer 1.0 API
from gi.repository import Gst, GLib 

# Everything we need from PyQt5: the widgets (buttons, labels, layouts), the image/picture classes for drawing frames, and the core bits for signals.
from PyQt5.QtWidgets import (   
    QApplication, QMainWindow, QWidget, QLabel,
    QHBoxLayout, QVBoxLayout, QPushButton, QComboBox, QFileDialog,
)
from PyQt5.QtGui import QImage, QPixmap 
from PyQt5.QtCore import Qt, QObject, pyqtSignal, QTimer 


# We force every frame to this exact size. Picking a fixed size up front saves a headache later: an RGB image that's 640 pixels wide is exactly 640*3 = 1920 bytes per row, with no leftover padding bytes, so PyQt reads the raw pixels correctly without us doing any awkward alignment maths.
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480


# 1. THE GSTREAMER SIDE
class CameraPipeline(QObject):
    """
    Owns the GStreamer pipeline and turns its frames into Qt signals.

    It is a QObject so it can emit signals. Two signals carry frames (one per
    feed); a third reports pipeline errors so the GUI can show them instead of
    failing silently.
    """

    # A frame is ready for feed 0 / feed 1. The QImage is already a private copy, so the GUI thread can keep it safely.
    frame_ready_0 = pyqtSignal(QImage)
    frame_ready_1 = pyqtSignal(QImage)
    # Something went wrong in the pipeline (e.g. camera permission denied).
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.pipeline = None
        self._bus_timer = None

    # Pipeline Construction
    def _build_description(self, use_test_source):
        """
        Return the GStreamer pipeline as a single launch string.

        `tee` is the key element: it duplicates the one live source into two
        identical branches. Each branch has its own `queue` (so the two feeds
        decouple and one can't stall the other) and its own `appsink`.

        appsink options explained:
            emit-signals=true  -> fire 'new-sample' so Python gets each frame
            max-buffers=1 drop=true -> only ever hold the newest frame; if the GUI is slow, drop stale frames instead of building up lag (right trade-off for live video -- freshness beats completeness)
            sync=false -> hand frames over as fast as they arrive
            caps=...RGB -> guarantee the bytes are plain RGB for drawing
        """
        if use_test_source:
            # No hardware needed: an animated SMPTE-style test pattern.
            source = "videotestsrc is-live=true pattern=ball"
        else:
            # macOS built-in / USB camera via AVFoundation.
            source = "avfvideosrc device-index=0"

        sink_opts = (
            "emit-signals=true max-buffers=1 drop=true sync=false "
            "caps=video/x-raw,format=RGB"
        )

        return (
            f"{source} ! videoconvert ! videoscale ! "
            f"video/x-raw,format=RGB,width={CAPTURE_WIDTH},height={CAPTURE_HEIGHT} ! "
            f"tee name=t "
            f"t. ! queue ! appsink name=sink0 {sink_opts} "
            f"t. ! queue ! appsink name=sink1 {sink_opts}"
        )

    def start(self, use_test_source=False):
        """(Re)build the pipeline and start playing."""
        self.stop()  # Tear down any previous run first

        description = self._build_description(use_test_source)
        try:
            # Parse_launch builds the whole element graph from the text above, exactly like the `gst-launch-1.0` command-line tool does.
            self.pipeline = Gst.parse_launch(description)
        except GLib.Error as exc:
            self.error.emit(f"Could not build pipeline: {exc}")
            return

        # Grab each appsink by the name we gave it and wire its 'new-sample' signal to our handler. The extra argument (0 or 1) tells the shared handler which feed the frame belongs to.
        self.pipeline.get_by_name("sink0").connect("new-sample", self._on_sample, 0)
        self.pipeline.get_by_name("sink1").connect("new-sample", self._on_sample, 1)

        # Poll the pipeline's message bus from the GUI thread for errors / EOS. A QTimer keeps this on the Qt event loop (no extra GLib main loop needed), which keeps the threading model as simple as possible.
        bus = self.pipeline.get_bus()
        self._bus_timer = QTimer()
        self._bus_timer.timeout.connect(lambda: self._poll_bus(bus))
        self._bus_timer.start(100)  # check 10x/second

        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        """Stop playback and release the pipeline and camera."""
        if self._bus_timer is not None:
            self._bus_timer.stop()
            self._bus_timer = None
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)  # Frees the camera
            self.pipeline = None

    # Per-frame callback (runs on a GStreamer streaming thread) 
    def _on_sample(self, appsink, which):
        """
        Called by GStreamer for every new frame. Convert it to a QImage and
        emit it. MUST stay thread-safe: no widget access here.
        """
        sample = appsink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK

        buf = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        width = caps.get_value("width")
        height = caps.get_value("height")

        # `map` gives us read access to the raw pixel bytes.
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.ERROR
        try:
            # Bytes-per-row. With our forced 640-wide RGB this is exactly  width*3 and 4-byte aligned, so QImage reads it correctly.
            stride = info.size // height
            # Wrap the bytes as a QImage, then COPY so we own the memory GStreamer frees `info` the instant we unmap below.
            image = QImage(
                bytes(info.data), width, height, stride, QImage.Format_RGB888
            ).copy()
        finally:
            buf.unmap(info)

        # Hand the frame to the GUI thread via a queued signal.
        if which == 0:
            self.frame_ready_0.emit(image)
        else:
            self.frame_ready_1.emit(image)
        return Gst.FlowReturn.OK

    # Bus Polling
    def _poll_bus(self, bus):
        """Drain pending bus messages; surface errors and end-of-stream."""
        msg = bus.timed_pop_filtered(
            0, Gst.MessageType.ERROR | Gst.MessageType.EOS
        )
        if msg is None:
            return
        if msg.type == Gst.MessageType.ERROR:
            err, _debug = msg.parse_error()
            self.error.emit(str(err))
        elif msg.type == Gst.MessageType.EOS:
            self.error.emit("Stream ended (end-of-stream).")

# 2. ONE VIDEO PANE (a reusable widget: title + picture + live FPS)
class VideoPane(QWidget):
    """A single feed's display: a heading, the video image, and an FPS read-out."""

    def __init__(self, title):
        super().__init__()
        self._last_image = None      # Keep the latest frame for snapshots
        self._frame_times = []       # Timestamps used to compute a rolling FPS

        # Heading above the video.
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        # The video itself lives in a QLabel; we set its pixmap each frame.
        self.video_label = QLabel("waiting for video…")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(CAPTURE_WIDTH, CAPTURE_HEIGHT)
        self.video_label.setStyleSheet("background-color: #111; color: #888;")

        # Small status line under the video.
        self.fps_label = QLabel("FPS: --")
        self.fps_label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout()
        layout.addWidget(self.title_label)
        layout.addWidget(self.video_label, stretch=1)
        layout.addWidget(self.fps_label)
        self.setLayout(layout)

    def update_frame(self, image):
        """Slot: receives a QImage on the GUI thread and draws it."""
        self._last_image = image

        # Scale to fit the label while preserving aspect ratio, so resizing the window never distorts the picture.
        pixmap = QPixmap.fromImage(image).scaled(
            self.video_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.video_label.setPixmap(pixmap)
        self._update_fps()

    def _update_fps(self):
        """Rolling frames-per-second over roughly the last second."""
        now = time.monotonic()
        self._frame_times.append(now)
        # Keep only timestamps from the last second
        self._frame_times = [t for t in self._frame_times if now - t < 1.0]
        self.fps_label.setText(f"FPS: {len(self._frame_times)}")

    def save_snapshot(self, path):
        """Write the most recent frame to disk; returns True on success."""
        if self._last_image is None:
            return False
        return self._last_image.save(path)


# 3. THE MAIN WINDOW (layout + controls, wiring pipeline to panes)
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dual Camera Feed — PyQt5 + GStreamer")

        # The two feeds, side by side. This is the "structured, intentional layout" the task asks for: equal panes, clearly labelled.
        self.pane0 = VideoPane("Feed 1  (live)")
        self.pane1 = VideoPane("Feed 2  (duplicated)")
        feeds = QHBoxLayout()
        feeds.addWidget(self.pane0)
        feeds.addWidget(self.pane1)

        # Control bar
        self.source_box = QComboBox()
        self.source_box.addItems(["Webcam (avfvideosrc)", "Test pattern (videotestsrc)"])

        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.snap_btn = QPushButton("Snapshot both")
        self.stop_btn.setEnabled(False)
        self.snap_btn.setEnabled(False)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Source:"))
        controls.addWidget(self.source_box)
        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.snap_btn)
        controls.addStretch(1)

        root = QVBoxLayout()
        root.addLayout(feeds, stretch=1)
        root.addLayout(controls)
        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)

        self.statusBar().showMessage("Idle. Pick a source and press Start.")

        # Pipeline + String Wiring
        self.pipeline = CameraPipeline()
        # Frames flow: GStreamer thread -> (queued signal) -> GUI slot.
        self.pipeline.frame_ready_0.connect(self.pane0.update_frame)
        self.pipeline.frame_ready_1.connect(self.pane1.update_frame)
        self.pipeline.error.connect(self._on_pipeline_error)

        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        self.snap_btn.clicked.connect(self._on_snapshot)

    # Button Handlers
    def _on_start(self):
        use_test = self.source_box.currentIndex() == 1
        self.pipeline.start(use_test_source=use_test)
        self.start_btn.setEnabled(False)
        self.source_box.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.snap_btn.setEnabled(True)
        self.statusBar().showMessage("Streaming…")

    def _on_stop(self):
        self.pipeline.stop()
        self.start_btn.setEnabled(True)
        self.source_box.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.snap_btn.setEnabled(False)
        self.pane0.video_label.setText("stopped")
        self.pane1.video_label.setText("stopped")
        self.statusBar().showMessage("Stopped.")

    def _on_snapshot(self):
        """Save both current frames. One dialog picks a base name; we suffix it."""
        base, _ = QFileDialog.getSaveFileName(
            self, "Save snapshots as…", "snapshot.png", "PNG image (*.png)"
        )
        if not base:
            return
        stem = base[:-4] if base.lower().endswith(".png") else base
        ok0 = self.pane0.save_snapshot(f"{stem}_feed1.png")
        ok1 = self.pane1.save_snapshot(f"{stem}_feed2.png")
        if ok0 and ok1:
            self.statusBar().showMessage(f"Saved {stem}_feed1.png and {stem}_feed2.png")
        else:
            self.statusBar().showMessage("Snapshot failed (no frame yet?).")

    def _on_pipeline_error(self, message):
        """Show pipeline errors in the status bar and reset the controls."""
        self.statusBar().showMessage(f"Error: {message}")
        self._on_stop()

    # Make sure the camera is released on quit
    def closeEvent(self, event):
        self.pipeline.stop()
        super().closeEvent(event)


# 4. ENTRY POINT
def main():
    # GStreamer must be initialised once, before any pipeline is built.
    Gst.init(None)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1320, 560)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()