// Platform detection for keyboard-shortcut gating.
//
// Different platforms reserve their modifier real estate differently:
//
//   macOS  — Cmd is the app modifier. Ctrl is sacred for terminal/Emacs
//            chords (Ctrl+B tmux prefix, Ctrl+P fish/zsh history, etc.).
//   Linux  — raw Ctrl belongs to the shell. Per the GNOME / Konsole /
//            xfce4-terminal / Alacritty / Ghostty / kitty convention,
//            apps use **Ctrl+Shift** for their shortcuts; raw Ctrl flows
//            through to the shell untouched.
//
// Treating Ctrl and Cmd as interchangeable (the original code) clobbers
// shell-side bindings on macOS; treating them as interchangeable on Linux
// hijacks Ctrl+P / Ctrl+B / Ctrl+F / Ctrl+N / Ctrl+W from readline.

export const IS_MAC = /Mac|iPod|iPhone|iPad/.test(navigator.platform);

/** True for the key event's "app modifier": Cmd on macOS, Ctrl+Shift on Linux. */
export function appMod(e: KeyboardEvent | MouseEvent): boolean {
  return IS_MAC ? e.metaKey : e.ctrlKey && e.shiftKey;
}
