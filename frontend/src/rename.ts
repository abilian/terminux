// Inline rename <input> — window.prompt is unavailable in pywebview's
// WKWebView. Commits on Enter/blur, cancels on Escape.

export function makeRenameInput(
  value: string,
  cls: string,
  commit: (next: string) => void,
  cancel: () => void,
): HTMLInputElement {
  const input = document.createElement("input");
  input.className = cls;
  input.value = value;
  input.spellcheck = false;
  let done = false;
  const finish = (save: boolean): void => {
    if (done) return;
    done = true;
    const next = input.value.trim();
    if (save && next && next !== value) commit(next);
    else cancel();
  };
  input.onkeydown = (e: KeyboardEvent): void => {
    e.stopPropagation();
    if (e.key === "Enter") finish(true);
    else if (e.key === "Escape") finish(false);
  };
  input.onblur = (): void => finish(true);
  input.onclick = (e: MouseEvent): void => e.stopPropagation();
  input.ondblclick = (e: MouseEvent): void => e.stopPropagation();
  setTimeout(() => {
    input.focus();
    input.select();
  }, 0);
  return input;
}
