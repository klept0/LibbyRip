#!/usr/bin/env python3
import os
import subprocess
import sys

try:
    subprocess.run(
        ("ffmpeg", "-version"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )
except FileNotFoundError:
    print("Error: FFmpeg not found, please install it on your system "
          "to continue: https://www.ffmpeg.org/download.html")
    sys.exit(1)

path = input("MP3 path: ")

if not os.path.exists(path):
    print("File not found")
    sys.exit(1)

if not (path.endswith(".mp3") or path.endswith(".MP3")):
    print('File MUST be an mp3 file to continue')
    sys.exit(1)

out_path = path[:-4] + ".m4b"

try:
    subprocess.run([
        "ffmpeg", "-i", path, "-c:a", "aac", "-b:a", "128k", "-vn",
        "-map_metadata", "0", "-map_chapters", "0", "-f", "ipod", out_path
    ], check=True)
    print(f"Successfully converted to: {out_path}")
except subprocess.CalledProcessError as e:
    print(f"Error during conversion: {e}")
    sys.exit(1)

