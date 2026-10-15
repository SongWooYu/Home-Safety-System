#!/usr/bin/env bash
set -euo pipefail

camera_id="${1:-}"
case "$camera_id" in
  cam3|webcam|dahua) ;;
  *) echo "Usage: $0 {cam3|webcam|dahua}" >&2; exit 2 ;;
esac

fps="${WEBRTC_FPS:-8}"
width="${WEBRTC_WIDTH:-640}"
height="${WEBRTC_HEIGHT:-360}"
bitrate_kbps="${WEBRTC_BITRATE_KBPS:-700}"
vision_url="${VISION_LOCAL_URL:-http://127.0.0.1:8080}"
rtsp_url="${MEDIAMTX_RTSP_URL:-rtsp://127.0.0.1:8554}"
gop=$((fps * 2))
bufsize_kbps=$((bitrate_kbps / 2))

exec ffmpeg -nostdin -hide_banner -loglevel warning \
  -r "$fps" -i "${vision_url}/stream/${camera_id}?fps=${fps}&overlay=false" \
  -an \
  -vf "scale=${width}:${height}:force_original_aspect_ratio=decrease:flags=fast_bilinear,pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2:black" \
  -c:v libx264 -preset ultrafast -tune zerolatency -threads 1 \
  -profile:v baseline -level:v 3.1 -pix_fmt yuv420p -bf 0 \
  -b:v "${bitrate_kbps}k" -maxrate "${bitrate_kbps}k" -bufsize "${bufsize_kbps}k" \
  -g "$gop" -keyint_min "$gop" -x264-params "scenecut=0" \
  -pkt_size 1200 -f rtsp -rtsp_transport tcp "${rtsp_url}/${camera_id}"
