#!/bin/bash
# installs ellen image sorter for your user, no sudo needed
# ./install.sh          normal install
# ./install.sh --ocr    also installs easyocr so it can read signatures (around 1GB)
set -e
cd "$(dirname "$0")"

APP="$HOME/.local/share/ellen-sorter"
BIN="$APP/venv/bin/ellen-sorter"

for thing in python3 ffmpeg ffprobe notify-send; do
    if ! command -v "$thing" >/dev/null; then
        echo "heads up, $thing isnt installed. install it with your package manager"
    fi
done

mkdir -p "$APP" "$HOME/.config/systemd/user" "$HOME/.local/share/applications"

# --system-site-packages so it can use pyside6 from your distro if you already have it
echo "making the venv..."
python3 -m venv --system-site-packages "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q .

if ! "$APP/venv/bin/python" -c "import PySide6" 2>/dev/null; then
    echo "pyside6 isnt installed, grabbing it for the gui..."
    "$APP/venv/bin/pip" install -q PySide6
fi

if [ "$1" = "--ocr" ]; then
    echo "installing easyocr (cpu version of torch so its not 5GB)..."
    "$APP/venv/bin/pip" install -q --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
    "$APP/venv/bin/pip" install -q --no-cache-dir easyocr
fi

cp horse.jpg "$APP/"
cp packaging/ellen-sorter.service "$HOME/.config/systemd/user/"
sed "s|ELLEN_SORTER_BIN|$BIN|" packaging/ellen-sorter.desktop > "$HOME/.local/share/applications/ellen-sorter.desktop"

# write the default settings file if there isnt one yet
"$APP/venv/bin/python" -c "import os; from ellensorter import config; os.path.exists(config.CONFIG_FILE) or config.save(config.load())"

systemctl --user daemon-reload
echo
echo "installed."
echo "open \"ellen image sorter\" from your app menu (or run $BIN gui), pick your folder, hit save"
echo "then hit start. or just run: systemctl --user enable --now ellen-sorter"
