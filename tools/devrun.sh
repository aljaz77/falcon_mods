#!/bin/bash
# Run JS inside a Falcon Design Space that has the dev hook (patcher.py install --dev).
#   tools/devrun.sh TAG script.js
# The statements run in Component.onCompleted of a throw-away Item; t(label, fn) logs a result.
# Output is collected from the app log (lines tagged FM-TAG). IMPORTS="import X" adds imports.
D="$LOCALAPPDATA/Falcon Design Space/falconmods/dev"
L="$LOCALAPPDATA/Falcon Design Space/Logs/fds_$(date +%Y-%m-%d).log"
TAG=$1; JS=$(cat "$2")
mkdir -p "$D"; rm -rf "$D"/*
R="$D/run_${TAG}_$(date +%s%N)"
S="$D.tmp"; rm -rf "$S"; mkdir -p "$S"; F="$S/run.qml"
while IFS= read -r x; do [ -n "$x" ] && cp "$x" "$S/"; done <<< "${EXTRA:-}"   # EXTRA: files (one per line) next to run.qml
T="$F"
cat > "$T" <<QML
import QtQuick 2.15
${IMPORTS:-}
Item {
    id: root
    function t(tag, f) { try { var r = f(); console.warn("FM-$TAG " + tag + " -> " + (typeof r === "object" ? JSON.stringify(r) : r)) } catch (e) { console.warn("FM-$TAG " + tag + " ERR " + e) } }
    Component.onCompleted: {
        $JS
        console.warn("FM-$TAG end")
    }
}
QML
mv "$S" "$R"          # appear complete, never half-written
for i in $(seq 1 ${WAIT:-40}); do grep -aq "FM-$TAG end" "$L" && break; sleep 1; done
rm -rf "$R"
grep -a "FM-$TAG \|run_${TAG}_" "$L" | sed 's/.*\] FM-/FM-/' | awk '!seen[$0]++'
