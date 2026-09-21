#!/usr/bin/env python3
"""Install portable Codex skills and a reversible global instruction block."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
START = '<!-- token-saver:start -->'
END = '<!-- token-saver:end -->'
STATE = 'token-saver/state.json'
LEGACY_SKILL_FILES = tuple(
    f'skills/{name}/{suffix}'
    for name, helper in [('muse-delegate', 'muse_worker.py'), ('jev-context', 'context_filter.py')]
    for suffix in ['SKILL.md', 'agents/openai.yaml', f'scripts/{helper}']
)
SKILL_FILES = LEGACY_SKILL_FILES + (
    'skills/muse-delegate/scripts/muse_evidence.py',
    'skills/muse-delegate/scripts/task_ledger.py',
)


def sha(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def guarded(home, relative):
    path = home / relative
    for part in [path, *path.parents]:
        if part == home:
            break
        if part.is_symlink():
            raise ValueError(f'Refusing symlink target: {part}')
    if path.exists() and not path.is_file():
        raise ValueError(f'Expected a file: {path}')
    return path


def current(path):
    return path.read_bytes() if path.exists() else None


def span(text):
    if not text.count(START) and not text.count(END):
        return None
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError('Malformed Token Saver markers in AGENTS.md; fix them before installing.')
    return text.index(START), text.index(END) + len(END)


def render(home, muse, jev):
    skill_root = str(home / 'skills')
    muse_rule = (
        f'Use `muse-delegate` at `{skill_root}/muse-delegate/SKILL.md` for delegated investigation, '
        'implementation, repetitive edits, and tests. Reserve Astra (or the explicitly configured primary model) '
        'for planning, difficult decisions, review, integration, and tiny tasks where delegation adds overhead. '
        'Do not automatically route work to Sol, Terra, Luna, explorer, or mechanical workers. '
        'The user enabled Muse during setup and authorizes '
        'sending task-relevant project excerpts to their configured Meta account across projects. '
        'Do not request that consent again. If Muse is blocked or Codex-specific tools are needed, '
        'have the primary agent handle the necessary work and report the fallback.'
        if muse else
        f'Use native workers when worthwhile. The optional `muse-delegate` skill is installed at '
        f'`{skill_root}/muse-delegate/SKILL.md`, but automatic Meta delegation is not enabled. '
        'Use it only after explicit user authorization; installation alone is not consent.'
    )
    jev_rule = (
        'The user enabled the Jev API during setup and authorizes task-relevant excerpts for TypeSafe '
        'across projects. Use it when semantic ranking justifies the request, with the user\'s own credentials.'
        if jev else
        'Automatic Jev API use is not enabled. Use the local backend unless the user explicitly '
        'authorizes sending the selected excerpts to TypeSafe.'
    )
    template = (ROOT / 'instructions/global.md').read_text(encoding='utf-8')
    body = template.replace('@@SKILLS_PATH@@', skill_root).replace('@@MUSE_POLICY@@', muse_rule).replace('@@JEV_POLICY@@', jev_rule)
    return START + '\n' + body.rstrip() + '\n' + END


def write_file(path, data, mode):
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.token-saver-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def apply_changes(changes, dry_run):
    changed = [(p, data, mode) for p, data, mode in changes if current(p) != data]
    for path, data, _ in changed:
        print(('Would remove ' if dry_run else 'Remove ') if data is None else
              ('Would write ' if dry_run else 'Write '), path, sep='')
    if dry_run or not changed:
        if not changed:
            print('Already up to date.')
        return
    before = [(p, current(p), stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o644)
              for p, _, _ in changed]
    try:
        for path, data, mode in changed:
            write_file(path, data, mode)
    except OSError:
        for path, data, mode in reversed(before):
            write_file(path, data, mode)
        raise


def load_state(home):
    path = guarded(home, STATE)
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('schema') != 1 or set(state.get('files', {})) not in (set(SKILL_FILES), set(LEGACY_SKILL_FILES)):
        raise ValueError('Unrecognized install state; preserve state.json and inspect it before proceeding.')
    return state


def install(home, muse=None, jev=None, dry_run=False):
    previous = load_state(home)
    agents_path = guarded(home, 'AGENTS.md')
    original_text = (current(agents_path) or b'').decode('utf-8')
    bounds = span(original_text)
    if bounds and not previous:
        raise ValueError('Found Token Saver instructions without install state; restore state.json first.')
    if previous and bounds and original_text[bounds[0]:bounds[1]] != previous['block']:
        raise ValueError('The managed instruction block was edited. Save your edits outside its markers first.')
    options = previous['options'] if previous else {'muse': False, 'jev_api': False}
    options = {'muse': options['muse'] if muse is None else muse,
               'jev_api': options['jev_api'] if jev is None else jev}
    block = render(home, options['muse'], options['jev_api'])
    separator = previous['separator'] if previous else ('\n\n' if original_text else '')
    if bounds:
        merged = original_text[:bounds[0]] + block + original_text[bounds[1]:]
    else:
        separator = '\n\n' if original_text else ''
        merged = original_text + separator + block
    state = {'schema': 1, 'version': (ROOT / 'VERSION').read_text().strip(),
             'options': options, 'block': block, 'separator': separator,
             'agents_existed': previous['agents_existed'] if previous else agents_path.exists(), 'files': {}}
    changes = []
    for relative in SKILL_FILES:
        destination = guarded(home, relative)
        old, new = current(destination), (ROOT / relative).read_bytes()
        old_entry = previous['files'].get(relative) if previous else None
        if old_entry and sha(old) not in (old_entry['installed_sha256'], sha(new), None):
            raise ValueError(f'Locally modified installed file; preserve or restore it first: {destination}')
        state['files'][relative] = {
            'original': old_entry['original'] if old_entry else
                        (base64.b64encode(old).decode('ascii') if old is not None else None),
            'original_mode': old_entry['original_mode'] if old_entry else
                             (stat.S_IMODE(destination.stat().st_mode) if destination.exists() else 0o644),
            'installed_sha256': sha(new),
        }
        changes.append((destination, new, 0o755 if '/scripts/' in relative else 0o644))
    changes.append((agents_path, merged.encode('utf-8'),
                    stat.S_IMODE(agents_path.stat().st_mode) if agents_path.exists() else 0o644))
    changes.append((guarded(home, STATE), (json.dumps(state, indent=2) + '\n').encode('utf-8'), 0o600))
    apply_changes(changes, dry_run)
    print(f'Preferences: Muse={options["muse"]}, Jev API={options["jev_api"]}; local filtering available.')


def uninstall(home, dry_run=False):
    state = load_state(home)
    if not state:
        print('Token Saver has no managed installation here.')
        return
    agents_path = guarded(home, 'AGENTS.md')
    text = (current(agents_path) or b'').decode('utf-8')
    bounds = span(text)
    if bounds and text[bounds[0]:bounds[1]] != state['block']:
        raise ValueError('The managed instruction block was edited. Save your edits outside its markers first.')
    changes = []
    for relative, entry in state['files'].items():
        path = guarded(home, relative)
        data = current(path)
        if data is not None and sha(data) != entry['installed_sha256']:
            raise ValueError(f'Uninstall stopped to preserve your edited file: {path}')
        restored = base64.b64decode(entry['original'], validate=True) if entry['original'] is not None else None
        changes.append((path, restored, entry['original_mode']))
    if bounds:
        before, after = text[:bounds[0]], text[bounds[1]:]
        separator = state['separator']
        if separator and before.endswith(separator):
            before = before[:-len(separator)]
        if before and after and not before.endswith('\n') and not after.startswith('\n'):
            before += '\n'
        remaining = before + after
        changes.append((agents_path, remaining.encode('utf-8') if remaining or state['agents_existed'] else None,
                        stat.S_IMODE(agents_path.stat().st_mode) if agents_path.exists() else 0o644))
    changes.append((guarded(home, STATE), None, 0o600))
    apply_changes(changes, dry_run)
    print('Only managed files and instructions were restored/removed; private settings and unrelated files remain.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=(ROOT / 'VERSION').read_text().strip())
    subparsers = parser.add_subparsers(dest='command', required=True)
    for command in ['install', 'uninstall', 'doctor']:
        sub = subparsers.add_parser(command)
        sub.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex'))
        if command != 'doctor':
            sub.add_argument('--dry-run', action='store_true')
        if command == 'install':
            sub.add_argument('--muse', action=argparse.BooleanOptionalAction, default=None,
                             help='Authorize automatic task-relevant Meta delegation; default off on first install')
            sub.add_argument('--jev-api', action=argparse.BooleanOptionalAction, default=None,
                             help='Authorize task-relevant TypeSafe calls; default off on first install')
    args = parser.parse_args()
    home = args.codex_home.expanduser().resolve()
    if args.command == 'install':
        install(home, args.muse, args.jev_api, args.dry_run)
    elif args.command == 'uninstall':
        uninstall(home, args.dry_run)
    else:
        state = load_state(home)
        print(json.dumps({'python': sys.version.split()[0], 'codex_home': str(home),
                          'muse_cli': shutil.which('muse'), 'git': shutil.which('git'),
                          'installed_version': state['version'] if state else None,
                          'options': state['options'] if state else None, 'network_called': False}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Token Saver: {exc}', file=sys.stderr)
        sys.exit(1)
