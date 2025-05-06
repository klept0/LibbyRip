#!/usr/bin/env python3
import os, subprocess

try:
    subprocess.run(("ffmpeg", "-version"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except FileNotFoundError as _:
    print("Error: FFmpeg not found, please install it on your system to continue: https://www.ffmpeg.org/download.html")
    exit(1)

path = input("MP3 path: ")

if not os.path.exists(path):
    print("File not found")
    exit(1)
if not(path.endswith(".mp3") or path.endswith(".MP3")):
    print('File MUST be an mp3 file to continue')
    exit(1)

outPath = path[:-4] + ".m4b"


subprocess.run([
    "ffmpeg", "-i", path, "-c:a", "aac", "-b:a", "128k", "-vn", "-map_metadata", "0", "-map_chapters", "0", "-f", "ipod", outPath

])

