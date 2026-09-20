@AGENTS.md

Claude-specific notes:
- `.agent/features/` is canonical for feature behaviour. `AGENTS.md` is canonical for workflow. This file carries only deltas and must never contradict either.
- Before editing any module, identify EVERY affected spec — grep `.agent/features/` for the file path, the identifier, and the user-visible behaviour, not just the obvious feature directory. Read `overview.md` AND every sub-spec in each affected directory, and walk the EARS list rather than skimming the prose.
- Update the spec in the same commit as the code: modify the EARS sentence to match the new behaviour, add requirements for new sub-behaviour, remove requirements for removed behaviour, and renumber downstream entries when you insert one.
- After editing, re-read each modified spec end-to-end against the diff and confirm every named identifier (setting key, command name, slot name, column name, unit, category) still exists in the code.
- If you spot a spec sentence that no longer matches the code — even one unrelated to your change — fix it in the same commit. Do not carry known drift forward.
- See `AGENTS.md → Self-contained and anonymous`. Nothing identifying the operator, their location or their infrastructure may be written here, in any file, including this one. Deployment is out of scope: if a task asks you to change how the bot is deployed, stop and say so rather than adding a manifest, a hostname or a path.
