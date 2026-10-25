// True while the user is typing in a text field outside the terminals (the
// palette, a rename, find). A terminal that finishes attaching late (a slow
// shell start) must not take the focus from it.
export function typingElsewhere(): boolean {
  const el = document.activeElement;
  if (el instanceof HTMLInputElement) {
    return true;
  }
  // xterm.js takes keyboard input through its own hidden textarea.
  return el instanceof HTMLTextAreaElement && el.closest(".xterm") === null;
}
