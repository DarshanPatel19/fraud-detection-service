# CLAUDE.md

This repository implements the Real-Time Fraud Detection Service described in SPEC.md. Follow the spec in order and treat each section as a single build slice.

## Working rules

- Read SPEC.md first and implement strictly one slice at a time.
- Never implement more than one slice in a single request.
- Do not move to the next slice until the current slice is complete and the relevant behavior is working.
- Write clear, conventional code. Naming and type hint rules are defined in the Code style section.
- Keep changes focused on the active slice; avoid speculative features or unrelated refactors.
- Never commit anything. Git operations are the user’s responsibility.
- Never add, modify, or commit SPEC.md. It is gitignored and must remain out of version control.
- Never reference SPEC.md by name in any committed file.
- Do not build or run the full service yet; keep the work scoped to the current slice and its immediate validation.

## Slice workflow

1. Identify the current slice in SPEC.md.
2. Implement only that slice and its direct supporting files.
3. Keep the implementation simple and conventional.
4. After finishing the slice, report every changed file and give a three-line summary for each file describing what it does.

## Change report format

After each slice, write a concise change report to reports/slice-<n>.md, creating the reports folder if needed. The reports folder is gitignored.

Use this shape:

- Files changed:
  - path/to/file
    - Line 1: what the file does.
    - Line 2: why it exists for this slice.
    - Line 3: any notable implementation detail or constraint.

At the end of the report, append the full contents of every file you created or changed in that slice. Each file must appear in its own fenced code block with the path as the heading.

## Repository conventions

- Prefer small, composable modules over large monolithic files.
- Use idiomatic Python and keep FastAPI entrypoints straightforward.
- Favor configuration-driven decisions when the spec calls for them.
- Keep comments focused on rationale and tradeoffs, not on obvious code.
- Document design rationale in code comments as engineering tradeoffs only. Never reference SPEC.md, interviews, or hiring in any committed file.

## Code style

- Write code the way an experienced engineer writes it under normal deadlines, not the way a tutorial or a code generator writes it.
- Comment only what is not obvious from the code. No comments restating what a line does. No docstrings on trivial functions.
- No emoji anywhere, in code, logs, output, or markdown.
- No decorative separators, banner comments, or ASCII art.
- Avoid words like comprehensive, robust, seamless, powerful, enhanced in comments and docs.
- Do not wrap everything in try/except. Handle errors where there is a real failure mode and let the rest raise.
- Keep names short and conventional. `db`, `req`, `cfg` are fine where scope is small. Do not use long descriptive names for short-lived local variables.
- Type hints on function signatures and public interfaces only, not on every local variable.
- Do not add features, config options, or abstraction layers the spec did not ask for.
- Prefer plain functions over classes unless state genuinely needs holding.
- Keep the README plain: no badge rows, no emoji headers, no marketing language.
- Leave the code slightly imperfect where perfection would be over-engineering. Real codebases have pragmatic choices in them.

## Important note

The source of truth for implementation order is SPEC.md. If a request would span multiple slices, handle the first slice only and stop until the next slice is requested explicitly.
