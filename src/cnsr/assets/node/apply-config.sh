#!/usr/bin/env bash
# apply-config.sh <id> [keep-stopped]
#
# Takes up the Xray config staged as config.new.json, and a changed compose.yml: restarts Xray,
# checks the REALITY handshake with the values in verify.env (verify-reality.sh deletes that file),
# and puts the old config back when either fails. Then it starts the SNI rotation service, which
# cnsr stopped, unless keep-stopped (a deployment starts it later, in its own step), and last
# writes one line to apply-result for cnsr to read:
#   <id> ok                      the new config runs
#   <id> rolled-back <why>       the old config runs; <why> is staged (there was no config.new.json),
#                                restart or handshake
#   <id> failed                  Xray did not restart with the old config either
#
# cnsr has systemd run it (systemd-run), so it finishes whatever becomes of the connection: this
# computer may reach the node through the node's own Xray, and then the restart cuts it.
# xray/.restart-pending exists from before the config changes until Xray has restarted, as in a
# deployment. Must parse and run under bash 3.2. CNSR_ROOT and CNSR_ROTATE_UNIT are for tests only.

set -uo pipefail
export LC_ALL=C
PATH="$PATH:/usr/local/sbin:/usr/sbin:/sbin"

ID=${1:?}
KEEP_STOPPED=${2:-}
ROOT=${CNSR_ROOT:-/opt/cnsr}
UNIT=${CNSR_ROTATE_UNIT:-/etc/systemd/system/cnsr-rotate.service}
CONF=$ROOT/xray/conf
CONFIG=$CONF/config.json
STAGED=$CONF/config.new.json
BEFORE=$CONF/config.before-apply.json
MARKER=$ROOT/xray/.restart-pending
VALUES=$ROOT/verify.env
RESULT=$ROOT/apply-result

# finish <outcome>: clean up, start the rotation service, then report.
finish() {
    rm -f "$VALUES" "$BEFORE"
    if [ -z "$KEEP_STOPPED" ] && [ -f "$UNIT" ]; then
        systemctl start cnsr-rotate.service </dev/null
    fi
    printf '%s %s\n' "$ID" "$1" >"$RESULT.tmp" && mv -f "$RESULT.tmp" "$RESULT"
    exit 0
}

# The restart the marker owes is done once this succeeds. `up` takes up a changed compose.yml or
# starts a container that is gone; the config is only read on a start.
restart() {
    docker compose -f "$ROOT/xray/compose.yml" up -d </dev/null &&
        docker compose -f "$ROOT/xray/compose.yml" restart </dev/null && rm -f "$MARKER"
}

# roll_back <why>: the old config again.
roll_back() {
    touch "$MARKER"
    if mv -f "$BEFORE" "$CONFIG" && restart; then
        finish "rolled-back $1"
    fi
    finish failed
}

[ -f "$STAGED" ] && cp -p "$CONFIG" "$BEFORE" || finish "rolled-back staged"
touch "$MARKER" && mv -f "$STAGED" "$CONFIG" || finish "rolled-back staged"
restart || roll_back restart
bash "$ROOT/bin/verify-reality.sh" "$VALUES" </dev/null || roll_back handshake
finish ok
