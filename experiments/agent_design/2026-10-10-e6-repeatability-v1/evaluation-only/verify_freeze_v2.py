"""Read-only integrity check; never prepares model content or semantic selections."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT = Path(__file__).resolve().parents[1]


def verify():
    freeze = json.loads((EXPERIMENT / 'evaluation-only/freeze.v2.json').read_bytes())
    checked = 0
    for name, base in (('files', EXPERIMENT), ('implementation_files', ROOT),
                       ('skill_files', ROOT), ('runtime_config_files', ROOT)):
        for relative, expected in freeze[name].items():
            actual = hashlib.sha256((base / relative).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError('frozen input changed: ' + relative)
            checked += 1
    gradients = json.loads((EXPERIMENT / 'gradients.v1.json').read_bytes())
    for tier in gradients['tiers']:
        dataset = ROOT / tier['dataset']
        manifest = dataset / 'manifest.json'
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != tier['dataset_manifest_sha256']:
            raise ValueError('frozen dataset manifest changed: ' + tier['tier_id'])
        for relative, expected in json.loads(manifest.read_bytes())['files'].items():
            if hashlib.sha256((dataset / relative).read_bytes()).hexdigest() != expected:
                raise ValueError('frozen dataset file changed: ' + relative)
            checked += 1
    return {'status': 'all_frozen_inputs_unchanged', 'files_checked': checked, 'model_calls': 0}


if __name__ == '__main__':
    print(json.dumps(verify()))
