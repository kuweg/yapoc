#!/bin/bash
# yapoc-supervisor.sh — auto-restarts YAPOC on crash/exit
#
# Exit code 0  = user chose to quit → stop.
# Exit code 42 = /reload requested  → restart silently.
# Non-zero     = crash              → restart with message.

# Ignore signals that the child might propagate up
trap '' INT TERM

while true; do
    # Run in a subshell that restores signal handling for the child
    (trap - INT TERM; exec poetry run yapoc)
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        break
    elif [ $EXIT_CODE -eq 42 ]; then
        echo "↺ Reloading YAPOC..."
        sleep 1
    else
        echo "💥 YAPOC exited ($EXIT_CODE), restarting in 2s..."
        sleep 2
    fi
done
