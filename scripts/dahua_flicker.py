#!/usr/bin/env python3
"""Read/adjust only Dahua antiflicker; default is a dry run, backup before SET."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests
from requests.auth import HTTPDigestAuth
from smarthome_vision.config import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    cfg = load_config("config/cameras.yaml")
    url = urlsplit(next(c["url"] for c in cfg["cameras"] if c["id"] == "dahua"))
    session = requests.Session()
    session.trust_env = False
    session.auth = HTTPDigestAuth(unquote(url.username), unquote(url.password))
    endpoint = f"http://{url.hostname}/cgi-bin/configManager.cgi"

    def read():
        result = {}
        for group in ("VideoInOptions", "VideoInExposure"):
            response = session.get(endpoint, params={"action": "getConfig", "name": group}, timeout=8)
            response.raise_for_status()
            for line in response.text.splitlines():
                key, sep, value = line.partition("=")
                if sep and key.endswith(".AntiFlicker"):
                    result[key.removeprefix("table.")] = int(value)
        if not result:
            raise RuntimeError("Camera returned no AntiFlicker settings; refusing to write")
        return result

    before = read()
    wanted = {key: 2 for key in before}  # Dahua API: 0 outdoor, 1 50Hz, 2 60Hz.
    if args.restore:
        snapshot = json.loads(args.restore.read_text())
        if snapshot["camera_host"] != url.hostname:
            raise RuntimeError("Backup belongs to a different camera")
        wanted = snapshot["antiflicker"]
        if not wanted or any(k not in before or v not in (0, 1, 2) for k, v in wanted.items()):
            raise RuntimeError("Backup contains unsupported settings")
    changes = {k: v for k, v in wanted.items() if before[k] != v}
    print(json.dumps({"before": before, "changes": changes, "apply": args.apply}))
    if not args.apply or not changes:
        return
    folder = Path("runtime/diagnostics/camera-backups")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = folder / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    with backup.open("x") as stream:
        json.dump({"camera_host": url.hostname, "antiflicker": before}, stream, indent=2)
    print(f"Backup: {backup}")
    response = session.get(endpoint, params={"action": "setConfig", **changes}, timeout=8)
    response.raise_for_status()
    if response.text.strip() != "OK":
        raise RuntimeError("Camera rejected SET; inspect current values and restore backup")
    after = read()
    if any(after.get(k) != v for k, v in wanted.items()):
        raise RuntimeError("Readback mismatch; restore the printed backup")
    print(json.dumps({"verified": after}))


if __name__ == "__main__":
    main()
