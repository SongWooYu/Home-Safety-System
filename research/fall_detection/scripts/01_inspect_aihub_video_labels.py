from pathlib import Path
from collections import Counter
import json

ROOTS = {
    "train": Path("data/aihub71641/labels/train"),
    "val": Path("data/aihub71641/labels/val"),
}

INTERESTING = (
    "key", "joint", "pose", "skeleton",
    "frame", "fall", "actor", "scene",
    "camera", "cam", "path"
)

def iter_video_json(root: Path):
    for path in root.rglob("*.json"):
        # 현재 확인한 JPG/BBOX 라벨은 제외
        if "이미지" in path.parts:
            continue
        yield path

def load(path):
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)

def walk(obj, prefix="", result=None):
    if result is None:
        result = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            p = f"{prefix}.{key}" if prefix else key
            result.append((p, type(value).__name__))
            walk(value, p, result)

    elif isinstance(obj, list) and obj:
        p = f"{prefix}[]"
        result.append((p, f"list[{len(obj)}]"))
        walk(obj[0], p, result)

    return result

all_files = {}

for split, root in ROOTS.items():
    files = list(iter_video_json(root))
    all_files[split] = files
    print(f"{split.upper()} VIDEO JSON: {len(files):,}")

print()

train_files = all_files["train"]

if not train_files:
    raise SystemExit(
        "이미지 이외 JSON을 찾지 못했습니다. "
        "위 디렉터리 목록을 확인해야 합니다."
    )

print("=" * 100)
print("FIRST VIDEO-LABEL PATHS")
print("=" * 100)

for path in train_files[:10]:
    print(path)

print()
print("=" * 100)
print("FIRST SAMPLE")
print("=" * 100)

sample = train_files[0]
data = load(sample)

print("PATH:", sample)
print(json.dumps(data, ensure_ascii=False, indent=2)[:12000])

print()
print("=" * 100)
print("INTERESTING FIELD PATHS")
print("=" * 100)

paths = walk(data)

for path, typ in paths:
    if any(word in path.lower() for word in INTERESTING):
        print(f"{path}: {typ}")

print()
print("=" * 100)
print("SCHEMA FREQUENCY - FIRST 500 VIDEO JSON")
print("=" * 100)

counter = Counter()

for path in train_files[:500]:
    try:
        obj = load(path)
        for field, typ in walk(obj):
            if any(word in field.lower() for word in INTERESTING):
                counter[(field, typ)] += 1
    except Exception as exc:
        print("READ ERROR:", path, exc)

for (field, typ), count in counter.most_common(100):
    print(f"{count:4d}  {field}: {typ}")
