#!/bin/sh
set -eu

SOURCE_PATH=$0
while [ -L "$SOURCE_PATH" ]; do
    SOURCE_DIR=$(CDPATH= cd "$(dirname "$SOURCE_PATH")" && pwd -P)
    LINK_TARGET=$(readlink "$SOURCE_PATH")
    case $LINK_TARGET in
        /*) SOURCE_PATH=$LINK_TARGET ;;
        *) SOURCE_PATH=$SOURCE_DIR/$LINK_TARGET ;;
    esac
done
REPO_DIR=$(CDPATH= cd "$(dirname "$SOURCE_PATH")" && pwd -P)
INSTALLER=$REPO_DIR/install.sh
BIN_DIR=$HOME/.local/bin
LAUNCHER=$BIN_DIR/worklog
PYTHON_RECORD=$BIN_DIR/.worklog-python

if [ "${0##*/}" = worklog ]; then
    RECORDED_PYTHON=
    if [ -r "$PYTHON_RECORD" ]; then
        IFS= read -r RECORDED_PYTHON < "$PYTHON_RECORD" || :
    fi

    if [ -n "$RECORDED_PYTHON" ] && [ -x "$RECORDED_PYTHON" ]; then
        PYTHON_PATH=$RECORDED_PYTHON
    else
        if [ -n "$RECORDED_PYTHON" ]; then
            echo "Recorded worklog interpreter $RECORDED_PYTHON is unavailable; falling back to python3 from PATH." >&2
        else
            echo "No recorded worklog interpreter was found; falling back to python3 from PATH." >&2
        fi
        if ! command -v python3 >/dev/null 2>&1; then
            echo "worklog fallback failed: python3 was not found on PATH." >&2
            exit 1
        fi
        if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
            PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
            echo "worklog fallback requires python3 3.10 or newer; found $PYTHON_VERSION." >&2
            exit 1
        fi
        PYTHON_PATH=$(python3 -c 'import sys; print(sys.executable)')
    fi

    if [ -n "${PYTHONPATH-}" ]; then
        PYTHONPATH=$REPO_DIR:$PYTHONPATH
    else
        PYTHONPATH=$REPO_DIR
    fi
    export PYTHONPATH
    exec "$PYTHON_PATH" -m worklog.cli "$@"
fi

TRIED_INTERPRETERS='python3, python3.14, python3.13, python3.12, python3.11, python3.10'
PYTHON_COMMAND=
NEWEST_VERSION=
NEWEST_VERSION_CODE=0

for CANDIDATE in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if ! CANDIDATE_PATH=$(command -v "$CANDIDATE" 2>/dev/null); then
        continue
    fi
    if ! CANDIDATE_INFO=$("$CANDIDATE_PATH" -c 'import sys; print("%d.%d.%d:%d" % (sys.version_info[0], sys.version_info[1], sys.version_info[2], sys.version_info[0] * 1000000 + sys.version_info[1] * 1000 + sys.version_info[2]))' 2>/dev/null); then
        continue
    fi
    CANDIDATE_VERSION=${CANDIDATE_INFO%%:*}
    CANDIDATE_VERSION_CODE=${CANDIDATE_INFO#*:}
    if [ "$CANDIDATE_VERSION_CODE" -gt "$NEWEST_VERSION_CODE" ]; then
        NEWEST_VERSION=$CANDIDATE_VERSION
        NEWEST_VERSION_CODE=$CANDIDATE_VERSION_CODE
    fi
    if [ "$CANDIDATE_VERSION_CODE" -ge 3010000 ]; then
        PYTHON_COMMAND=$CANDIDATE_PATH
        break
    fi
done

if [ -z "$PYTHON_COMMAND" ]; then
    if [ -n "$NEWEST_VERSION" ]; then
        FOUND_DETAIL="newest version found was $NEWEST_VERSION"
    else
        FOUND_DETAIL="none of those interpreters was found"
    fi
    echo "worklog requires Python 3.10 or newer. Tried $TRIED_INTERPRETERS; $FOUND_DETAIL." >&2
    exit 1
fi

PYTHON_PATH=$("$PYTHON_COMMAND" -c 'import sys; print(sys.executable)')
case $PYTHON_PATH in
    /*) ;;
    *) PYTHON_PATH=$(CDPATH= cd "$(dirname "$PYTHON_PATH")" && pwd -P)/$(basename "$PYTHON_PATH") ;;
esac

if [ ! -f "$REPO_DIR/worklog/cli.py" ]; then
    echo "install.sh must be run from a worklog checkout." >&2
    exit 1
fi

mkdir -p "$BIN_DIR"

if [ -L "$LAUNCHER" ]; then
    INSTALLED_TARGET=$(readlink "$LAUNCHER")
    if [ "$INSTALLED_TARGET" != "$INSTALLER" ]; then
        echo "$LAUNCHER already points to $INSTALLED_TARGET; leaving it unchanged." >&2
        exit 1
    fi
elif [ -e "$LAUNCHER" ]; then
    echo "$LAUNCHER already exists and is not a symlink; leaving it unchanged." >&2
    exit 1
else
    ln -s "$INSTALLER" "$LAUNCHER"
fi

(umask 077 && printf '%s\n' "$PYTHON_PATH" > "$PYTHON_RECORD")

echo "Installed worklog launcher at $LAUNCHER"

case :${PATH-}: in
    *:"$BIN_DIR":*) ;;
    *)
        echo "Warning: $BIN_DIR is not on PATH." >&2
        echo 'Add this line to your shell profile:' >&2
        echo 'export PATH="$HOME/.local/bin:$PATH"' >&2
        ;;
esac

echo
echo "Next, run: worklog doctor"
echo
echo "Claude Code hook (merge this into ~/.claude/settings.json):"
HOOK_COMMAND_JSON=$("$PYTHON_PATH" -c 'import json, shlex, sys; print(json.dumps("PYTHONPATH=%s %s -m worklog.hook" % (shlex.quote(sys.argv[1]), shlex.quote(sys.argv[2]))))' "$REPO_DIR" "$PYTHON_PATH")
echo "{
  \"hooks\": {
    \"UserPromptSubmit\": [
      {
        \"hooks\": [
          {
            \"type\": \"command\",
            \"command\": $HOOK_COMMAND_JSON
          }
        ]
      }
    ]
  }
}"
echo "install.sh does not modify ~/.claude/settings.json."
