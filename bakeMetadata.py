#!/usr/bin/env python3
import sys
import os
import json
import eyed3
import mimetypes
import argparse
import logging
from typing import Optional, Callable
from eyed3.id3 import ID3_V2_4
from PyQt5 import QtWidgets, QtCore


class GuiLogHandler(logging.Handler):
    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self.callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.callback(msg)
        except (RecursionError, Exception):
            self.handleError(record)


def bake_metadata(working_dir: str,
                  progress_callback: Optional[
                      Callable[[str, int], None]] = None) -> None:
    """
    Bake metadata into audiobook MP3 files.
    
    Args:
        working_dir: Directory containing audiobook files and metadata
        progress_callback: Optional callback for progress updates
    """
    if working_dir.startswith("'"):
        working_dir = working_dir[1:-1]
    
    # Sort the working list alphabetically
    working_list = sorted(os.listdir(working_dir))

    if "metadata" not in working_list:
        error_msg = (
            "ERROR: Working directory MUST contain a metadata directory. "
            "Remember to click the 'Export audiobook' button in the website!"
        )
        if progress_callback:
            progress_callback(error_msg, 0)
        raise FileNotFoundError(error_msg)

    metadata_dir = os.path.join(working_dir, "metadata")
    cover_files = [f for f in os.listdir(metadata_dir)
                   if f.startswith("cover")]
    
    if len(cover_files) != 1:
        error_msg = "ERROR: Cover art not found"
        if progress_callback:
            progress_callback(error_msg, 0)
        raise FileNotFoundError(error_msg)

    # Read cover art once
    cover_path = os.path.join(metadata_dir, cover_files[0])
    with open(cover_path, "rb") as f:
        cover_bytes = f.read()
    cover_mime = mimetypes.guess_type(cover_files[0])[0]

    # Open JSON file with UTF-8 encoding
    metadata_path = os.path.join(metadata_dir, "metadata.json")
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    # Extract author name more efficiently
    author_name = "Unknown"
    for creator in metadata["creator"]:
        if creator["role"] == "author":
            author_name = creator["name"]
            break

    # Build chapters dictionary
    chapters = {}
    for chap in metadata["chapters"]:
        chapters.setdefault(chap["spine"], []).append(chap)

    # Collect all parts to process
    parts = [file for file in working_list if file.startswith("Part ")]
    total = len(parts)
    if total == 0:
        error_msg = "ERROR: No parts found to process."
        if progress_callback:
            progress_callback(error_msg, 0)
        raise FileNotFoundError(error_msg)

    for index, file in enumerate(parts):
        number = file[len("Part "):].split(".")[0]
        spine_index = int(number) - 1

        audiofile = eyed3.load(os.path.join(working_dir, file))
        if audiofile.tag is None:
            # Initialize ID3v2.4 explicitly (UTF-8)
            audiofile.initTag(version=ID3_V2_4)
        else:
            audiofile.tag.clear()

        # Ensure we work with V2.4 and UTF-8
        audiofile.tag.version = ID3_V2_4

        audiofile.tag.title = f"Part {int(number)}"
        audiofile.tag.artist = author_name
        audiofile.tag.images.set(3, cover_bytes, cover_mime)
        audiofile.tag.album = metadata["title"]
        audiofile.tag.track_num = (int(number), len(metadata["spine"]))

        # Get chapters for this spine index
        spine_chapters = chapters.get(spine_index, [])
        if spine_chapters:
            # Check for non-increasing offsets
            prev_offset = spine_chapters[0]["offset"]
            for i, chap in enumerate(spine_chapters[1:], start=1):
                current_offset = chap["offset"]
                if current_offset <= prev_offset:
                    # Found overlapping chapter - report and exit
                    error_parts = [
                        f"ERROR: {metadata_path} has errors with "
                        f"overlapping chapter times.",
                        f"Look in chapters for spine: {spine_index}",
                        f"Chapter '{spine_chapters[i-1]['title']}' at "
                        f"offset: {spine_chapters[i-1]['offset']}",
                        f"Chapter '{chap['title']}' at offset: "
                        f"{current_offset}"
                    ]

                    # Format for current mode
                    if (progress_callback and
                            hasattr(progress_callback, '__self__')):
                        error_msg = "<br>".join(error_parts)
                    else:
                        error_msg = "\n".join(error_parts)

                    # Only send via exception, not progress callback
                    raise ValueError(error_msg)
                prev_offset = current_offset

        # Process chapters normally since offsets are valid
        last = None
        child_ids = []

        for i, chap in enumerate(chapters.get(int(number) - 1, [])):
            if last is None:
                last = chap
                continue
            cid = f"ch{i}".encode("ascii")
            child_ids.append(cid)
            c = audiofile.tag.chapters.set(
                cid,
                (int(last["offset"]) * 1000, int(chap["offset"]) * 1000 - 1)
            )
            c.title = last["title"]
            last = chap

        if last is not None:
            c = audiofile.tag.chapters.set(
                b"last",
                (
                    int(last["offset"]) * 1000,
                    int(metadata["spine"][last["spine"]]["duration"] * 1000)
                )
            )
            c.title = last["title"]

        audiofile.tag.table_of_contents.set(
            b"toc",
            toplevel=True,
            child_ids=child_ids + [b"last"],
            description="Table of Contents"
        )

        # Save as v2.4 so UTF-8 characters (umlauts) are correct
        audiofile.tag.save(version=ID3_V2_4)

        # Update progress
        if progress_callback:
            progress = int((index + 1) * 100 / total)
            progress_callback(f"Baked: {file}", progress)

# Worker class to run bake_metadata in a separate thread
class Worker(QtCore.QObject):
    progress = QtCore.pyqtSignal(str, int)
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            bake_metadata(self.path, progress_callback=self.progress.emit)
        except Exception as e:
            # Format for GUI if needed
            if "\n" in str(e):
                msg = str(e).replace("\n", "<br>")
            else:
                msg = str(e)
            self.error.emit(msg)
        finally:
            self.finished.emit()

# -------- GUI SECTION --------

class MetadataBakerApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bake Metadata")
        self.resize(500, 300)
        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout()

        # Directory selection
        dir_layout = QtWidgets.QHBoxLayout()
        self.dirInput = QtWidgets.QLineEdit()
        self.browseBtn = QtWidgets.QPushButton("Browse")
        dir_layout.addWidget(self.dirInput)
        dir_layout.addWidget(self.browseBtn)

        # Run button
        self.runBtn = QtWidgets.QPushButton("Run Bake")

        # Progress bar
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)

        # Log output
        self.logOutput = QtWidgets.QTextEdit()
        self.logOutput.setReadOnly(True)
        self.logOutput.setAcceptRichText(True)

        layout.addLayout(dir_layout)
        layout.addWidget(self.runBtn)
        layout.addWidget(self.progressBar)
        layout.addWidget(self.logOutput)
        self.setLayout(layout)

        self.browseBtn.clicked.connect(self.select_dir)
        self.runBtn.clicked.connect(self.run_bake)

    def select_dir(self):
        dir_path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Audiobook Directory")
        if dir_path:
            self.dirInput.setText(dir_path)

    def run_bake(self):
        path = self.dirInput.text().strip()
        self.logOutput.clear()

        if not os.path.isdir(path):
            self.logOutput.append("<span style='color:red;'>Invalid directory path.</span>")
            return

        self.progressBar.setValue(0)
        self.runBtn.setEnabled(False)
        self.browseBtn.setEnabled(False)

        self.thread = QtCore.QThread()
        self.worker = Worker(path)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.update_status)
        self.worker.error.connect(self.report_error)
        self.worker.finished.connect(self.process_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def update_status(self, message, progress):
        # Only display non-error messages here
        if not message.startswith("ERROR"):
            # Convert newlines to HTML line breaks for GUI
            if "\n" in message:
                message = message.replace("\n", "<br>")
            self.logOutput.append(message)
        self.progressBar.setValue(progress)

    def report_error(self, error_message):
        # Ensure error messages are properly formatted for GUI
        if "\n" in error_message:
            error_message = error_message.replace("\n", "<br>")
        self.logOutput.append(f"<span style='color:red;'>{error_message}</span>")

    def process_finished(self):
        self.logOutput.append("Processing complete.")
        self.runBtn.setEnabled(True)
        self.browseBtn.setEnabled(True)

# -------- MAIN ENTRY POINT --------

def main():
    parser = argparse.ArgumentParser(description="Bake audiobook metadata.")
    parser.add_argument("directory", nargs="?", default=None, help="Path to audiobook directory")
    parser.add_argument("--gui", action="store_true", help="Run in GUI mode")
    args = parser.parse_args()

    def cli_callback(message, progress):
        # Only display non-error messages here
        if not message.startswith("ERROR"):
            print(f"{message} ({progress}%)")

    if args.gui:
        app = QtWidgets.QApplication(sys.argv)
        window = MetadataBakerApp()
        if args.directory:
            window.dirInput.setText(args.directory)

        def gui_log_callback(message, progress=0):
            # Only display non-error messages here
            if not message.startswith("ERROR"):
                QtCore.QMetaObject.invokeMethod(
                    window.logOutput,
                    "append",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, message)
                )

        gui_handler = GuiLogHandler(lambda msg: gui_log_callback(msg))
        gui_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        gui_handler.setLevel(logging.WARNING)
        eyed3.log.addHandler(gui_handler)
        eyed3.log.propagate = False

        window.show()
        sys.exit(app.exec_())
    else:
        if args.directory:
            workingDir = args.directory
        else:
            workingDir = input("Path to audiobook dir: ").strip()
        try:
            bake_metadata(workingDir, progress_callback=cli_callback)
        except Exception as e:
            print(f"\033[91m{e}\033[0m")
            sys.exit(1)

if __name__ == "__main__":
    main()
