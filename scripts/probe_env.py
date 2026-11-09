"""Print a machine-readable inventory without changing the environment."""
import importlib.metadata as metadata
import json
import struct
import sys
try:
    from packaging.requirements import Requirement
except ImportError:
    from pip._vendor.packaging.requirements import Requirement
requirements=[]
for line in open(sys.argv[1], encoding='utf-8'):
    line=line.strip()
    if line and not line.startswith('#'): requirements.append(Requirement(line))
missing=[]; matched=0
for req in requirements:
    if req.marker and not req.marker.evaluate(): continue
    try: version=metadata.version(req.name)
    except metadata.PackageNotFoundError: version=None
    if version is not None and req.specifier.contains(version): matched+=1
    else: missing.append(str(req))
print(json.dumps(dict(python=sys.executable,venv=sys.prefix!=sys.base_prefix,
    compatible=sys.version_info>=(3,10) and struct.calcsize('P')==8,
    matched=matched,total=len(requirements),missing=missing)))
