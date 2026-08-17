#!/bin/zsh

set -eu

readonly LABEL="com.hanxiaobo.codex-msu2-display"
readonly DOMAIN="gui/$(/usr/bin/id -u)"
readonly PROJECT_DIR="${0:A:h}"
readonly SOURCE_PLIST="$PROJECT_DIR/$LABEL.plist"
readonly AGENTS_DIR="$HOME/Library/LaunchAgents"
readonly INSTALLED_PLIST="$AGENTS_DIR/$LABEL.plist"

if [[ ! -f "$SOURCE_PLIST" ]]; then
    print -u2 "找不到服务配置：$SOURCE_PLIST"
    exit 1
fi

if /bin/launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    /bin/launchctl bootout "$DOMAIN" "$INSTALLED_PLIST"
    /bin/rm -f "$INSTALLED_PLIST"
    print "OFF"
else
    /bin/mkdir -p "$AGENTS_DIR"
    /bin/cp "$SOURCE_PLIST" "$INSTALLED_PLIST"
    /usr/bin/plutil -lint "$INSTALLED_PLIST" >/dev/null
    /bin/launchctl bootstrap "$DOMAIN" "$INSTALLED_PLIST"
    /bin/launchctl kickstart -k "$DOMAIN/$LABEL"
    print "ON"
fi
