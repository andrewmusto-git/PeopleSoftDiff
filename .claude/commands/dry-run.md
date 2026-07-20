Follow the **OAA Dry-Run Tester** workflow defined in CLAUDE.md.

Arguments provided by the user: $ARGUMENTS

- If no arguments are given, default to Mode A (local dry-run).
- If the arguments mention "lab", "push", or include an env file path, use Mode B.
- Start at Step 1 (Discover Integrations) unless the arguments already specify which integration to test.
