"""加载 server/presets/manifest.json，把模特图片登记进 AssetStore，供 /files/ 访问。"""
from __future__ import annotations

import json
from pathlib import Path

from outfit_core.bootstrap import SERVER_ROOT

PRESETS_DIR = SERVER_ROOT / "presets"


class PresetRecord:
    def __init__(self, manifest_entry: dict, image_asset):
        self.id = manifest_entry["id"]
        self.name = manifest_entry["name"]
        self.body = manifest_entry["body"]
        self.internal_only = manifest_entry.get("internal_only", False)
        self.image_asset = image_asset  # outfit_core.types.Asset，本地已落盘，sha256 已填充

    def to_response(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "body": self.body,
            "image": {"url": f"/files/{self.image_asset.sha256}", "mime": self.image_asset.mime},
            "internal_only": self.internal_only,
        }


def load_presets(store, presets_dir: Path = PRESETS_DIR) -> dict[str, PresetRecord]:
    manifest_path = presets_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records: dict[str, PresetRecord] = {}
    for entry in manifest.get("items", []):
        image_path = presets_dir / entry["image"]
        asset = store.put_file(image_path)
        records[entry["id"]] = PresetRecord(entry, asset)
    return records
