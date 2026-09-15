<!--
File: AGENTS.md
Summary: Persistent repository guidance for documentation and change-history practices.
Modified by: Eric Freeman
Last modified: 2026-09-15
-->

# Repository Guidance

## Documentation

- Begin every new or modified human-authored file that supports comments with a documentation
  header containing the filename, its purpose, `Eric Freeman` as the modifier, and the modification
  date in `YYYY-MM-DD` format.
- Add documentation comments to every function and method. State its purpose, describe each
  parameter, and describe the returned value when it returns one. Protocol and framework overrides
  may use concise descriptions but must still document parameters and non-void returns.
- Do not add invalid comments to formats that prohibit them, such as strict JSON, or to binary and
  generated assets. Document those files in the nearest README instead.
- Update relevant README files when setup, operation, architecture, or user workflows change.
- Keep `CHANGELOG.md` current with user-visible and operational changes.
- Update a file's modification date whenever making a substantive change to it.

## Change Scope

- Apply these documentation rules to files changed for the current task. Do not rewrite unrelated
  existing files solely to add headers or comments.
