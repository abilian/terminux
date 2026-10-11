// Elements that index.html always has: a missing one is a broken page,
// so fail at the lookup instead of carrying on with a null.
export function byId(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) {
    throw new Error(`#${id} is missing from index.html`);
  }
  return el;
}
