#!/bin/bash
# removes ellen image sorter. your pictures and settings are left alone
# ./uninstall.sh --all   also deletes the settings, catalog and logs
systemctl --user disable --now ellen-sorter.service 2>/dev/null
rm -f "$HOME/.config/systemd/user/ellen-sorter.service" "$HOME/.local/share/applications/ellen-sorter.desktop"
systemctl --user daemon-reload
rm -rf "$HOME/.local/share/ellen-sorter/venv"
if [ "$1" = "--all" ]; then
    rm -rf "$HOME/.local/share/ellen-sorter" "$HOME/.config/ellen-sorter" "$HOME/.local/state/ellen-sorter"
fi
echo "uninstalled"
