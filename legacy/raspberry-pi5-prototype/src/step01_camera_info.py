import subprocess
import platform
from pathlib import Path


def run_cmd(cmd: list[str]) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )
        return result.stdout.strip() or result.stderr.strip()
    except Exception as e:
        return f"ERROR: {e}"


def main():
    print("========== System Info ==========")
    print(f"Python     : {platform.python_version()}")
    print(f"Platform   : {platform.platform()}")
    print()

    print("========== Raspberry Pi Model ==========")
    model_path = Path("/proc/device-tree/model")
    if model_path.exists():
        print(model_path.read_text(errors="ignore").strip())
    else:
        print("Unknown model")
    print()

    print("========== Temperature ==========")
    print(run_cmd(["vcgencmd", "measure_temp"]))
    print()

    print("========== rpicam Commands ==========")
    for cmd in ["rpicam-hello", "rpicam-still", "rpicam-vid"]:
        print(f"{cmd}: {run_cmd(['which', cmd])}")
    print()

    print("========== Camera List ==========")
    print(run_cmd(["rpicam-hello", "--list-cameras"]))


if __name__ == "__main__":
    main()
