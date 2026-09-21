# Skill and plugin audit

Review worksheet, not an automatic uninstaller. Save filled copies under `work/` so they stay outside the release ZIP. Start with descriptions; read detailed instructions only where needed.

| Skill/plugin | Actual use | Overlap | Proposed choice | Reason |
| --- | --- | --- | --- | --- |
| Name | Task types | Alternative | Keep / explicit-only / disable | Evidence |

- **Keep** distinct, frequently useful capabilities.
- **Explicit-only skill:** set `policy.allow_implicit_invocation: false` in its `agents/openai.yaml`, preserving other metadata, when occasional use is helpful but automatic activation is not.
- **Disable unused skill:** use a `[[skills.config]]` entry with its absolute `SKILL.md` path and `enabled = false` in Codex configuration. Preserve other entries and keep a backup.
- **Plugin:** review its skills and tools together before disabling it through supported application settings. One redundant skill does not make every tool redundant.

Apply the user's chosen changes, then verify remaining workflows. Do not modify authentication or unrelated settings. Codex loads skills progressively and caps the initial catalog; explicit-only controls routing, not necessarily metadata size. Do not equate removed skill count with saved usage. [Official configuration](https://learn.chatgpt.com/docs/build-skills)
