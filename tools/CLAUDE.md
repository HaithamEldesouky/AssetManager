## Approach
- Read existing files before writing. Don't re-read unless changed.
- Concise in output.
- Skip files over 100KB unless required.
- Keep `.ps1` files pure ASCII (no emojis, no em-dashes): Windows PowerShell 5.1 reads a BOM-less file as cp1252 and a stray non-ASCII byte breaks parsing.
- Do not guess APIs, versions, flags, commit SHAs, or package names. Verify by reading code or docs before asserting.
