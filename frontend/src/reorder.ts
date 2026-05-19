// Mouse-event reordering for the sidebar and tab bar. HTML5 DnD and Pointer
// Events both proved unreliable in pywebview's WKWebView; classic mouse
// events are the lowest common denominator every WebKit supports.

const DRAG_THRESHOLD = 5; // px before a press becomes a drag
let lastDropAt = 0;
let dragging = false;

/** Move `from` to sit just before (or after, if `after`) `to` in `ids`
 * (pure). `after` is what lets an item land in the final slot. */
export function reorder(
  ids: string[],
  from: string,
  to: string,
  after = false,
): string[] {
  if (from === to) return ids.slice();
  const a = ids.slice();
  const fi = a.indexOf(from);
  if (fi < 0) return ids;
  a.splice(fi, 1);
  const ti = a.indexOf(to);
  if (ti < 0) {
    a.push(from);
    return a;
  }
  a.splice(after ? ti + 1 : ti, 0, from);
  return a;
}

/** True briefly after a reorder drop, so the synthetic click that follows
 * a mouse drag doesn't also activate the workspace/tab. */
export function recentlyReordered(): boolean {
  return Date.now() - lastDropAt < 250;
}

/** True while a reorder drag is in progress (pause poll re-renders). */
export function isReordering(): boolean {
  return dragging;
}

export function makeDraggable(
  el: HTMLElement,
  id: string,
  current: () => string[],
  commit: (order: string[]) => void,
): void {
  el.dataset.reorderId = id;
  el.addEventListener("mousedown", (down: MouseEvent) => {
    if (down.button !== 0) return;
    const target = down.target as HTMLElement;
    // Don't start a drag from interactive bits (rename input, ✎, ✕).
    if (target.closest("input, .x, .edit")) return;
    down.preventDefault(); // suppress text selection / native drag
    const sx = down.clientX;
    const sy = down.clientY;
    let active = false;
    let marked: HTMLElement | null = null;
    let after = false;

    const mark = (next: HTMLElement | null, side: boolean): void => {
      if (next === marked && side === after) return;
      marked?.classList.remove("drop-before", "drop-after");
      next?.classList.add(side ? "drop-after" : "drop-before");
      marked = next;
      after = side;
    };
    const onMove = (e: MouseEvent): void => {
      if (!active) {
        if (Math.hypot(e.clientX - sx, e.clientY - sy) < DRAG_THRESHOLD) return;
        active = true;
        dragging = true;
        el.classList.add("dragging");
        document.body.style.userSelect = "none";
        document.body.style.cursor = "grabbing";
      }
      // Live drop indicator on the prospective target. Which half of the
      // target the cursor is in decides before/after — the "after" case is
      // the only way to land in the final slot.
      const over = document.elementFromPoint(e.clientX, e.clientY);
      const host = over?.closest<HTMLElement>("[data-reorder-id]") ?? null;
      if (!host || host === el) {
        mark(null, false);
        return;
      }
      const r = host.getBoundingClientRect();
      const horizontal = !!host.closest("#tabbar");
      const side = horizontal
        ? e.clientX > r.left + r.width / 2
        : e.clientY > r.top + r.height / 2;
      mark(host, side);
    };
    const onUp = (): void => {
      document.removeEventListener("mousemove", onMove, true);
      document.removeEventListener("mouseup", onUp, true);
      if (!active) return; // it was a click; let the normal handler run
      const to = marked?.dataset.reorderId;
      const dropAfter = after;
      mark(null, false);
      el.classList.remove("dragging");
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      dragging = false;
      lastDropAt = Date.now();
      if (to && to !== id) commit(reorder(current(), id, to, dropAfter));
    };
    // Capture phase on document: fires even if a child stops propagation,
    // and mousemove is delivered while the button is held in every WebKit.
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("mouseup", onUp, true);
  });
}
