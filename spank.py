#!/usr/bin/env python3
"""
SPANK - Plays an audio file when your Mac detects a vibration/tap.
Uses the internal microphone to detect sudden impacts.
"""

import argparse
import subprocess
import time
import sys
import os

import numpy as np
import sounddevice as sd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Try common audio formats
for ext in ("mp3", "aiff", "wav", "m4a"):
    _candidate = os.path.join(SCRIPT_DIR, "sounds", f"spank.{ext}")
    if os.path.exists(_candidate):
        DEFAULT_SOUND = _candidate
        break
else:
    DEFAULT_SOUND = os.path.join(SCRIPT_DIR, "sounds", "spank.mp3")

last_trigger = 0


def play_sound(path):
    subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_callback(threshold, cooldown, sound_path):
    def callback(indata, frames, time_info, status):
        global last_trigger
        volume = np.sqrt(np.mean(indata ** 2))
        if volume > threshold and time.time() - last_trigger > cooldown:
            last_trigger = time.time()
            print(f"  SPANK! (volume: {volume:.4f})", flush=True)
            play_sound(sound_path)
    return callback


def main():
    parser = argparse.ArgumentParser(description="Play a sound when vibration is detected")
    parser.add_argument("-s", "--sound", default=DEFAULT_SOUND, help="Path to audio file (mp3/wav/aiff)")
    parser.add_argument("-t", "--threshold", type=float, default=0.05, help="Detection sensitivity (lower = more sensitive, default: 0.05)")
    parser.add_argument("-c", "--cooldown", type=float, default=2.0, help="Seconds between triggers (default: 2.0)")
    parser.add_argument("--list-devices", action="store_true", help="List audio input devices")
    parser.add_argument("-d", "--device", type=int, default=None, help="Input device index")
    args = parser.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        return

    if not os.path.exists(args.sound):
        print(f"Audio file not found: {args.sound}")
        print("Put your audio file in sounds/spank.mp3 or use -s <path>")
        sys.exit(1)

    print(f"SPANK detector running")
    print(f"  Sound:     {args.sound}")
    print(f"  Threshold: {args.threshold}")
    print(f"  Cooldown:  {args.cooldown}s")
    print(f"  Press Ctrl+C to stop\n")

    cb = make_callback(args.threshold, args.cooldown, args.sound)

    try:
        with sd.InputStream(callback=cb, channels=1, samplerate=44100, device=args.device):
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped.")
    except sd.PortAudioError as e:
        print(f"Audio error: {e}")
        print("Try --list-devices and pick one with -d <index>")
        sys.exit(1)


if __name__ == "__main__":
    main()
