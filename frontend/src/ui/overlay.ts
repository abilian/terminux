// A modal card mounted once on <body> and toggled: Escape or close()
// hides it and hands focus back to the terminal. Shared by the stats and
// connect-info overlays.

import { render, type VNode } from "preact";

import { activeSession } from "../state/store";

export interface Overlay {
  install: () => void;
  open: () => void;
  close: () => void;
  rerender: () => void;
  isVisible: () => boolean;
}

/**
 * `view(visible, key)` renders the card; `key` changes on every open, so
 * the card remounts and re-grabs focus. `onClose` runs before the hide.
 */
export function createOverlay(
  view: (visible: boolean, key: number) => VNode,
  onClose: () => void = () => {},
): Overlay {
  let host: HTMLDivElement | null = null;
  let visible = false;
  let epoch = 0;

  const rerender = (): void => {
    if (host) {
      render(view(visible, epoch), host);
    }
  };
  const close = (): void => {
    onClose();
    visible = false;
    rerender();
    activeSession()?.term.focus();
  };
  const ensure = (): void => {
    if (!host) {
      host = document.createElement("div");
      // Capture phase: xterm's textarea consumes Escape in its own
      // keydown, so we must run before it (same pattern as the keymap).
      window.addEventListener(
        "keydown",
        (e: KeyboardEvent) => {
          if (visible && e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            close();
          }
        },
        true,
      );
    }
    if (!host.isConnected) {
      document.body.appendChild(host);
    }
    rerender();
  };

  return {
    install: ensure,
    open: (): void => {
      visible = true;
      epoch++;
      ensure();
    },
    close,
    rerender,
    isVisible: () => visible,
  };
}
