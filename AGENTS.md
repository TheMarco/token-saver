# Token Saver development

Keep this package portable and small. Runtime and tests use Python 3.10+ standard library only. Follow the user's global delegation preferences; bounded workers may own non-overlapping files, while the primary agent reviews and integrates.

- Never package credentials, local settings, private prompts, session logs, caches, or machine-specific paths. Fixtures must be synthetic.
- Preserve existing user instructions and private skill settings during install/update. Keep cloud-service authorization explicit and separate from merely installing a skill.
- Run `python3 -m unittest discover -s tests -v` and an install/uninstall round trip into a temporary Codex home after installer changes. Tests must not make network/model calls.
- Build the archive with `python3 scripts/build_release.py`; its explicit file list is the distribution boundary. Update that list when adding package files.
- Avoid promises about subscription savings. Character counts measure selected output, and provider calls have their own costs and latency.
