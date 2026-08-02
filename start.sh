#!/bin/bash
# Export s6 container environment vars
for f in /run/s6/container_environment/*; do
  export "$(basename "$f")=$(cat "$f")"
done
export TZ=Asia/Shanghai
apk add --no-cache python3 py3-pip py3-pillow 2>&1 | tail -3
echo "Starting app..."
python3 /data/app.py
