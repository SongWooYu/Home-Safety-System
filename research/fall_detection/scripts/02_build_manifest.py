from pathlib import Path
import json
import re
import pandas as pd

ROOT = Path("data/aihub71641/labels/val/영상")
OUT = Path("data/aihub71641/manifests/val_manifest.csv")

rows = []

for path in ROOT.rglob("*.json"):
    with path.open("r", encoding="utf-8-sig") as f:
        d = json.load(f)

    meta = d["metadata"]
    scene = d["scene_info"]
    actor = d["actor_info"]
    sensor = d["sensordata"]

    scene_id = meta["scene_id"]

    # 같은 사건을 촬영한 C1~C8 영상을 하나의 그룹으로 묶음
    scenario_id = re.sub(r"_C\d+$", "", scene_id)

    rows.append({
        "scene_id": scene_id,
        "scenario_id": scenario_id,
        "camera": int(scene["cam_num"]),
        "is_fall": 1 if scene["scene_IsFall"] == "낙상" else 0,
        "fall_class": scene["scene_cat_name"],
        "fall_type": scene["fall_type"],
        "location": scene["scene_loc"],
        "position": scene["scene_pos"],
        "method": scene["scene_method"],
        "scene_length": int(scene["scene_length"]),
        "fall_start_frame": int(sensor["fall_start_frame"]),
        "fall_end_frame": int(sensor["fall_end_frame"]),
        "actor_id": actor["actor_id"],
        "actor_age": actor["actor_age"],
        "actor_sex": actor["actor_sex"],
        "scene_path": d["scene_path"]["scene_path"],
        "label_path": str(path),
    })

df = pd.DataFrame(rows).sort_values(["scenario_id", "camera"])
OUT.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUT, index=False, encoding="utf-8-sig")

print("manifest:", OUT)
print("clips:", len(df))
print("unique scenarios:", df["scenario_id"].nunique())

print("\nFall:")
print(df["is_fall"].value_counts().sort_index())

print("\nFall class:")
print(df["fall_class"].value_counts())

print("\nCamera:")
print(df["camera"].value_counts().sort_index())

print("\nActor IDs:")
print(df["actor_id"].value_counts())

print("\nViews per scenario:")
print(df.groupby("scenario_id").size().value_counts().sort_index())
