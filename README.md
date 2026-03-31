# SPANK

Plays an audio file when your Mac detects a vibration or tap.

Uses the internal microphone to detect sudden impacts (desk tap, laptop slap, etc.).

## Setup

```bash
pip install -r requirements.txt
```

Put your audio file at `sounds/spank.mp3` (supports mp3, wav, aiff).

## Usage

```bash
# Basic - detect vibrations and play sound
python spank.py

# Custom sound file
python spank.py -s /path/to/sound.mp3

# More sensitive (lower threshold)
python spank.py -t 0.05

# Less sensitive
python spank.py -t 0.3

# Shorter cooldown between triggers
python spank.py -c 1.0

# List audio devices
python spank.py --list-devices

# Use specific microphone
python spank.py -d 2
```

## Run at startup (optional)

```bash
# Add to your shell profile
echo 'nohup python ~/spank/spank.py &' >> ~/.zshrc
```

## How it works

1. Monitors the Mac's microphone for sudden volume spikes (vibrations produce low-frequency noise picked up by the mic)
2. When the volume exceeds the threshold, plays the audio file via `afplay`
3. Cooldown prevents repeated triggers from a single event
