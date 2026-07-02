#!/bin/bash
# The gt911 touch controller on the Touch Display 2 sometimes fails its
# kernel boot-time I2C probe (~3s into boot) because its power rail hasn't
# stabilized yet, especially with the ReSpeaker HAT sharing the GPIO header.
# Retry the bind a few seconds after boot once things have settled.
DEV="11-005d"
DRIVER="Goodix-TS"
for i in $(seq 1 10); do
    if [ -e "/sys/bus/i2c/devices/$DEV/driver" ]; then
        exit 0  # already bound
    fi
    echo "$DEV" > "/sys/bus/i2c/drivers/$DRIVER/bind" 2>/dev/null
    sleep 2
    if [ -e "/sys/bus/i2c/devices/$DEV/driver" ]; then
        logger "goodix-touch-rebind: bound successfully after $i attempt(s)"
        exit 0
    fi
done
logger "goodix-touch-rebind: failed to bind after 10 attempts"
exit 1
