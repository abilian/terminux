# Future considerations

This file lists design questions we have left open on purpose. Each entry states the question, what we know, the options, and what's blocking a decision.

---

## Unified command palette

**Question.** Should we collapse the quick switcher (`Cmd+P` / `Ctrl+Shift+P`) and the command palette (`Cmd+Shift+P` / `F1`) into a single overlay?

**Background.** The two-palette split came from VS Code:

- **Quick switcher** lists workspaces and tabs; selecting one jumps to it.
- **Command palette** lists verbs (Sort by activity, Reset counters, Display usage stats, Toggle prefs…); selecting one runs the verb.

On Linux the two-palette model is awkward: the natural app-modifier chord is `Ctrl+Shift+P`, which already maps to the quick switcher. The "+ Shift" trick that distinguishes the two palettes on macOS isn't free on Linux, where Ctrl+Shift is already the modifier. We currently work around that by binding the command palette to `F1` on Linux as a provisional stop-gap. It works but it's asymmetric and a little ad-hoc.

A unified palette dissolves the split: one overlay, one chord, mixed results.

**Options.**

1. **Unify (one palette).** `Cmd+Shift+P` / `Ctrl+Shift+P` opens it. Commands and workspaces mingle. Match fuzzy across both. Selecting either does the right thing. Same UX both platforms.
2. **Keep split, change Linux chord.** Use `F1` permanently or pick a different binding (`Ctrl+Shift+;`?). The semantics stay symmetric, but the chords differ.
3. **Keep split, swap the Linux assignments.** Make `Ctrl+Shift+P` open the command palette on Linux and use `Ctrl+P` (clobbering shell history) for the quick switcher. **No**: this is exactly what we just decided not to do.

**Leaning toward (1), unified.** The split has never mattered much; both palettes do "fuzzy-pick from a list and run the highlighted result." The UX question is how to keep that one overlay legible.

**UX/UI bar to clear before shipping (1).**

The unification only works if the merged list reads cleanly *without asking the user to think about it*. Concrete musts:

- **Visual grouping.** Commands and workspaces are different kinds of things. They need a subtle but unmistakable visual distinction (an icon, a badge ("⚡" for command, "◆" for workspace), or a tinted left bar), beyond label text. The cue has to hold up under fuzzy filtering: when results collapse to two rows from different sections, the cue must still be there.
- **Sensible default order.** Empty query opens with commands first or workspaces first? Lean toward **commands first**, since the user opened the palette on purpose, but the most-recently-used workspace should bubble high. One option puts commands above a separator and workspaces below, both filterable.
- **Section labels** (or no labels?). VS Code uses inline section headers ("recently opened" / "files"). Slack does the same. They cost a row of vertical space but eliminate ambiguity. We should experiment, with mocks before code.
- **Detail column.** Workspaces want a right-aligned active time (`27m 14s`). Commands want either nothing or a current-state hint (`on` / `off` for toggles). Same column, different content. The font, alignment and opacity must already be in place; the current `pal-detail` style provides them.
- **Keyboard semantics on Enter.** A command runs; a workspace switches. Both close the palette. Mismatched primary actions are fine as long as the user understands which row type they're on.
- **No "command mode" prefix.** Avoid VS Code's `>` prefix to switch to command mode: it's a workaround for ambiguity that this design should remove. If we end up needing a prefix, the unification has failed.
- **Default shortcut behaves the same on both platforms** for the same action. If Cmd/Ctrl+P opens "the palette," that's the only palette.

**Open sub-questions.**

- What happens to the existing `Cmd+P` (quick switcher only) chord on macOS? Does it disappear entirely, or do we keep it as a faster path to "just workspaces"? The argument for keeping it is muscle memory from VS Code users. Argument against: erodes the unification.
- The activity stats overlay (`Display usage stats`) lives outside the palette. Does the workspace-row detail column eliminate the need for the overlay too? Probably not: the overlay shows session totals, relative bars, and "session started X ago" which the palette row can't fit.

**Decision blockers.** Mockups. The merge only works if a five-row mixed list is instantly legible to a stranger. Before coding, sketch the layout with realistic content (8 workspaces × 5 commands) and check that:

1. A new user can tell what each row does without reading the label.
2. Typing 3 chars filters cleanly without ambiguity.
3. The "command rows always sticky at top" rule (if we adopt it) doesn't confuse arrow-key navigation.

If those pass, ship it and retire `F1`.
