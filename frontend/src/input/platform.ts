// Platform detection for keyboard-shortcut gating.
//
// Different platforms reserve their modifier real estate differently:
//
//   macOS  — Cmd is the app modifier, and so is Ctrl+Shift, so the Linux
//            and Windows chords work on a Mac too. Plain Ctrl is sacred for
//            terminal/Emacs chords (Ctrl+B tmux prefix, Ctrl+P history...).
//   Linux  — raw Ctrl belongs to the shell. Per the GNOME / Konsole /
//            xfce4-terminal / Alacritty / Ghostty / kitty convention,
//            apps use **Ctrl+Shift** for their shortcuts; raw Ctrl flows
//            through to the shell, except Ctrl+V and Ctrl+C with a
//            selection (copy and paste, as on Windows; see keymap.ts).
//
// Treating Ctrl and Cmd as interchangeable (the original code) clobbers
// shell-side bindings on macOS; treating them as interchangeable on Linux
// hijacks Ctrl+P / Ctrl+B / Ctrl+F / Ctrl+N / Ctrl+W from readline.

export const IS_MAC = /Mac|iPod|iPhone|iPad/.test(navigator.platform);

/** True for the key event's "app modifier": Ctrl+Shift, or Cmd on macOS. */
export function appMod(e: KeyboardEvent): boolean {
  return (e.ctrlKey && e.shiftKey) || (IS_MAC && e.metaKey);
}

/** True in a browser tab, false in terminux's own window (pywebview defines ``window.pywebview``). */
export function inBrowser(): boolean {
  return !("pywebview" in window);
}

/**
 * A fallback modifier for browser tabs on Linux and Windows, where the
 * browser keeps some Ctrl+Shift chords for itself (T, W, N, and P in
 * Firefox): Alt+Shift, which no browser binds. keymap.ts takes it for
 * those chords only; shells bind the rest (Alt+Shift+- is M-_). A Mac has
 * Ctrl+Shift besides Cmd already.
 */
export function browserMod(e: KeyboardEvent): boolean {
  return (
    !IS_MAC && inBrowser() && e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey
  );
}

/** The link-opening modifier: Cmd+click on macOS, plain Ctrl+click elsewhere. */
export function linkMod(e: MouseEvent): boolean {
  return IS_MAC ? e.metaKey : e.ctrlKey;
}
