"""Build a review ZIP without local operations files or dependencies."""

from pathlib import Path
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
version = json.loads((ROOT / "package.json").read_text())["version"]
files = [
    "main.py",
    "plugin.json",
    "package.json",
    "dist/index.js",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
]
files += [
    str(p.relative_to(ROOT))
    for p in sorted((ROOT / "licenses").iterdir())
    if p.is_file()
]
for name in files:
    if not (ROOT / name).is_file():
        raise SystemExit(f"Required file is missing: {name}")
output = ROOT / "dist" / f"touchscreen-toggle-{version}-review.zip"
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for name in files:
        archive.write(ROOT / name, f"touchscreen-toggle/{name}")
print(output)
