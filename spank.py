#!/usr/bin/env python3
"""
SPANK - Plays audio when your Mac detects movement/vibration.
Uses a low-pass filter on the microphone to isolate physical
vibrations (taps, bumps, movement) from voices and ambient noise.
"""

import argparse
import subprocess
import time
import sys
import os

import numpy as np
import sounddevice as sd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for ext in ("mp3", "aiff", "wav", "m4a"):
    _candidate = os.path.join(SCRIPT_DIR, "sounds", f"spank.{ext}")
    if os.path.exists(_candidate):
        DEFAULT_SOUND = _candidate
        break
else:
    DEFAULT_SOUND = os.path.join(SCRIPT_DIR, "sounds", "spank.mp3")

SAMPLERATE = 44100
LOWPASS_HZ = 300  # Only keep frequencies below 300Hz (vibrations, not voice)

last_trigger = 0
baseline_rms = 0.0
baseline_samples = 0


def lowpass(data, cutoff, fs):
    """Simple FFT-based low-pass filter."""
    fft = np.fft.rfft(data.flatten())
    freqs = np.fft.rfftfreq(len(data), 1.0 / fs)
    fft[freqs > cutoff] = 0
    return np.fft.irfft(fft, len(data))


def play_sound(path):
    subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_callback(threshold, cooldown, sound_path, sensitivity):
    def callback(indata, frames, time_info, status):
        global last_trigger, baseline_rms, baseline_samples

        # Low-pass filter: keeps only vibration frequencies, kills voice/music
        filtered = lowpass(indata, LOWPASS_HZ, SAMPLERATE)
        rms = float(np.sqrt(np.mean(filtered ** 2)))

        # Build baseline over first 2 seconds (~100 callbacks at 1024 frames)
        if baseline_samples < 100:
            baseline_rms = (baseline_rms * baseline_samples + rms) / (baseline_samples + 1)
            baseline_samples += 1
            if baseline_samples == 100:
                print(f"  Baseline calibrated: {baseline_rms:.6f}", flush=True)
            return

        # Trigger if current RMS is X times above baseline
        spike = rms / max(baseline_rms, 1e-8)

        if spike > sensitivity and time.time() - last_trigger > cooldown:
            last_trigger = time.time()
            print(f"  SPANK! (spike: {spike:.1f}x, rms: {rms:.5f})", flush=True)
            play_sound(sound_path)

        # Slowly adapt baseline (ignore spikes)
        if spike < sensitivity * 0.5:
            baseline_rms = baseline_rms * 0.995 + rms * 0.005

    return callback


def main():
    parser = argparse.ArgumentParser(description="Play a sound when movement/vibration is detected")
    parser.add_argument("-s", "--sound", default=DEFAULT_SOUND, help="Path to audio file")
    parser.add_argument("-x", "--sensitivity", type=float, default=4.0,
                        help="Spike multiplier over baseline to trigger (default: 4.0, lower = more sensitive)")
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

    print("SPANK motion detector")
    print(f"  Sound:       {args.sound}")
    print(f"  Sensitivity: {args.sensitivity}x baseline")
    print(f"  Cooldown:    {args.cooldown}s")
    print(f"  Filter:      <{LOWPASS_HZ}Hz (vibrations only)")
    print(f"  Calibrating baseline (2s, don't move)...\n")

    cb = make_callback(0, args.cooldown, args.sound, args.sensitivity)

    try:
        with sd.InputStream(callback=cb, channels=1, samplerate=SAMPLERATE, device=args.device):
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
