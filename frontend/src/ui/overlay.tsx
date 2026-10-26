// A modal card mounted on <body> at first open and toggled: Escape or
// close() hides it and hands focus back to the terminal. Shared by every
// overlay: both palettes, find, stats and connect-info.

import { render, type ComponentChildren, type VNode } from "preact";
import { useLayoutEffect, useRef } from "preact/hooks";

import { activeSession } from "../state/store";

export interface Overlay {
  open: () => void;
  close: () => void;
  rerender: () => void;
  isVisible: () => boolean;
}

/**
 * `view(visible, key)` renders the card; `key` changes on every open, so a
 * card keyed on it remounts (fresh state, focus re-grabbed), and one that
 * ignores it keeps its state between opens. `onClose` runs before the hide.
 * A `modal` overlay closes on Escape wherever focus is; a non-modal one
 * (find) handles Escape itself, so the terminal and other inputs keep it.
 */
export function createOverlay(
  view: (visible: boolean, key: number) => VNode,
  {
    onClose = () => {},
    modal = true,
  }: { onClose?: () => void; modal?: boolean } = {},
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
          if (modal && visible && e.key === "Escape") {
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

interface ModalProps {
  id: string;
  cardId: string;
  visible: boolean;
  onClose: () => void;
  children: ComponentChildren;
}

/** A backdrop (a click on it closes) around a card that takes focus on
 * mount, so Escape lands there rather than on the still-focused xterm
 * textarea, which would feed ESC to the shell. Key it per open. */
export function Modal({ id, cardId, visible, onClose, children }: ModalProps) {
  const card = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => card.current?.focus(), []);
  return (
    <div
      id={id}
      hidden={!visible}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div id={cardId} tabIndex={-1} ref={card}>
        {children}
      </div>
    </div>
  );
}
