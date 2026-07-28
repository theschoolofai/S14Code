"""Extract the raw attack surface from turn_4.json for validator round-tripping."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from generate_live import extract, normalize

raw = json.loads(pathlib.Path("proofs/part2/turn_4.json").read_text(encoding="utf-8"))["raw"]
surface = normalize(extract(raw))
# Keep dict-shaped components only (adversarial output can include non-dicts).
surface["components"] = [c for c in surface.get("components", []) if isinstance(c, dict)]
pathlib.Path("proofs/part2/turn_4_raw_surface.json").write_text(
    json.dumps(surface, indent=2), encoding="utf-8"
)
print("wrote turn_4_raw_surface.json")
print("component types in raw:", sorted({c["type"] for c in surface["components"]}))
