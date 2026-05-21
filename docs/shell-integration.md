# Shell integration — reliable "ready" attention

terminux fires the sidebar attention badge (🔔) on three signals from the
shell:

| Signal | What it means | Triggered by |
| --- | --- | --- |
| **Real BEL** (`\x07` outside an OSC) | Legacy "ding" | `printf '\\a'`, `echo -e '\\a'` |
| **OSC 9** | iTerm2-style desktop notification | `printf '\x1b]9;%s\x07' "done!"` |
| **OSC 133;D** | A long-running command just finished — *the* "ready" signal | shell integration (below) |

The BEL that closes an `OSC 0/2;<title>\x07` title update **does not count**
— tools like Claude Code update the title constantly while they work, and
the sidebar would never stop ringing if it counted those.

## Why you want OSC 133

OSC 133;D is the only one of the three that fires when a command actually
finishes. Set it up once and:

- Background tabs only ping you when their work is done.
- Tabs you're already looking at never ping you (the attention guard is
  per-tab visibility).
- Quick commands (`cd`, `ls` — anything under ~2 seconds) stay silent;
  only commands worth waiting for raise the badge.
- The sidebar's amber **busy** dot (see
  [Working vs ready](workspaces-and-tabs.md#working-vs-ready)) becomes
  precise: it lights only between the shell's `;C` and `;D` markers,
  instead of flagging every interactive TUI as "running."

You need a small snippet in your shell init file. Pick yours:

=== "zsh"

    Add to `~/.zshrc`:

    ```zsh
    if [[ -n "$TERMINUX_SESSION" || "$TERM_PROGRAM" == "terminux" ]]; then
      _osc133_preexec() { print -n "\e]133;C\e\\"; }
      _osc133_precmd()  { print -Pn "\e]133;D;%?\e\\"; print -n "\e]133;A\e\\"; }
      autoload -Uz add-zsh-hook
      add-zsh-hook preexec _osc133_preexec
      add-zsh-hook precmd  _osc133_precmd
    fi
    ```

=== "bash"

    Add to `~/.bashrc`:

    ```bash
    if [[ "$TERM_PROGRAM" == "terminux" ]]; then
      _osc133_DEBUG() { printf '\e]133;C\e\\'; }
      _osc133_PROMPT() { printf '\e]133;D;%s\e\\' "$?"; printf '\e]133;A\e\\'; }
      trap '_osc133_DEBUG' DEBUG
      PROMPT_COMMAND='_osc133_PROMPT'"${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
    fi
    ```

=== "fish"

    Add to `~/.config/fish/config.fish`:

    ```fish
    if test "$TERM_PROGRAM" = terminux
      function _osc133_preexec --on-event fish_preexec
        printf '\e]133;C\e\\'
      end
      function _osc133_postexec --on-event fish_postexec
        printf '\e]133;D;%s\e\\' $status
        printf '\e]133;A\e\\'
      end
    end
    ```

!!! note "Why guard on `TERM_PROGRAM`"
    Other terminals (Ghostty, iTerm2 with their own integration, …) may
    interpret OSC 133 differently or run their own version. Guarding makes
    the snippet inert outside terminux. terminux sets
    `TERM_PROGRAM=terminux` in every shell it spawns.

## How it works

terminux watches each PTY's output for `OSC 133;C` (command start) and
`OSC 133;D[;exit]` (command end). When `;D` arrives, the attention badge
fires **only if** the matching `;C` was at least **2 seconds** earlier and
the tab isn't currently in view — so a snappy `cd` in a background tab
won't ring, but a long `make test` or a Claude Code response will.

The threshold is hard-coded in `core/terminal.py`
(`OSC133_MIN_COMMAND_SECONDS`); it's deliberately not user-configurable yet.
