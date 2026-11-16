"""Build an installable ZIP using Decky's runtime directory layout."""

import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
package = json.loads((ROOT / "package.json").read_text())
name, version = package["name"], package["version"]
files = [
    "main.py",
    "plugin.json",
    "package.json",
    "dist/index.js",
    "dist/index.js.map",
    "bin/touchscreen-control",
    "README.md",
    "LICENSE",
    "defaults/licenses/decky-api.LICENSE",
    "defaults/licenses/decky-template.BSD-3-Clause.txt",
    "defaults/licenses/font-awesome.LICENSE",
]
for filename in files:
    if not (ROOT / filename).is_file():
        raise SystemExit(f"Required file is missing: {filename}")
output = ROOT / "dist" / f"{name}-{version}.zip"
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for filename in files:
        installed = filename.removeprefix("defaults/")
        archive.write(ROOT / filename, f"{name}/{installed}")
print(output)
