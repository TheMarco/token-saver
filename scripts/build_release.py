#!/usr/bin/env python3
"""Build a portable ZIP from an explicit allowlist; never include local state."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'README.md', 'VERSION', 'LICENSE', '.gitignore', 'AGENTS.md', 'install.py',
    'instructions/global.md', 'docs/WORKFLOW.md', 'docs/PRIVACY.md', 'docs/OPTIMIZING.md',
    'docs/TESTING.md', 'docs/SKILL_AUDIT.md', 'docs/SETTINGS.md',
    'templates/HANDOFF.md', 'templates/TASK_BRIEF.md', 'templates/TASK_SCORECARD.csv',
    'templates/PROJECT_MAP.md',
    'scripts/build_release.py', 'tests/test_install.py', 'tests/test_helpers.py',
    'examples/investigate.txt', 'examples/implement.txt',
    'skills/muse-delegate/SKILL.md', 'skills/muse-delegate/agents/openai.yaml',
    'skills/muse-delegate/scripts/muse_worker.py',
    'skills/muse-delegate/scripts/muse_evidence.py',
    'skills/muse-delegate/scripts/task_ledger.py',
    'tests/test_evidence.py', 'tests/test_ledger.py', 'docs/EVIDENCE.md',
    'skills/jev-context/SKILL.md', 'skills/jev-context/agents/openai.yaml',
    'skills/jev-context/scripts/context_filter.py',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text().strip()
    output = args.output or ROOT / 'dist' / f'token-saver-{version}.zip'
    sources = [ROOT / name for name in FILES]
    for source in sources:
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'Missing or symlinked package file: {source}')
    if output.resolve() in {p.resolve() for p in sources}:
        raise ValueError('Archive output cannot overwrite a source file')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, source in zip(FILES, sources):
            archive.write(source, f'token-saver-{version}/{name}')
    print(f'{output.resolve()}\n{len(FILES)} files\nSHA256 {hashlib.sha256(output.read_bytes()).hexdigest()}')


if __name__ == '__main__':
    main()
