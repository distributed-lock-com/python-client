from __future__ import annotations

import os

from dunamai import Style, Version

version = Version.from_git().serialize(style=Style.SemVer)

with open("distributed_lock/__init__.py") as f:
    c = f.read()

lines = []
for line in c.splitlines():
    if line.startswith("VERSION = "):
        lines.append(f'VERSION = "{version}"')
    else:
        lines.append(line)

with open("distributed_lock/__init__.py", "w") as g:
    g.write("\n".join(lines))

print(f"Setting version={version}")
os.system(f"poetry version {version}")
