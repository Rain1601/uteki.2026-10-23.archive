"""Terminate a synthetic HTML stage after some files, before the manifest."""
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.content import publication
from uteki.data_platform.build.pipeline import build_bundle

with Catalog.open(Path(sys.argv[1])) as catalog:
    build=catalog.get_build(sys.argv[2]);files,manifest=build_bundle(catalog,build)
    original=publication.write_control
    def interrupted(path,raw,**kwargs):
        if path.name=='tables.jsonl':os._exit(73)
        return original(path,raw,**kwargs)
    with patch.object(publication,'write_control',side_effect=interrupted):
        publication.Publication(catalog).stage(build['build_id'],files=files,manifest=manifest)
