// @vitest-environment jsdom
// A terminal attaching late must not steal the focus from a text field.

import { afterEach, describe, expect, it } from "vitest";

import { typingElsewhere } from "../src/util/focus";

afterEach(() => {
  document.body.innerHTML = "";
});

function focused<T extends HTMLElement>(
  el: T,
  parent: HTMLElement = document.body,
): T {
  parent.append(el);
  el.focus();
  return el;
}

describe("typingElsewhere", () => {
  it("is false when nothing has the focus", () => {
    expect(typingElsewhere()).toBe(false);
  });

  it("is true in an input (the palette, a rename, find)", () => {
    focused(document.createElement("input"));
    expect(typingElsewhere()).toBe(true);
  });

  it("is false in a terminal's own textarea", () => {
    const xterm = document.createElement("div");
    xterm.className = "xterm";
    document.body.append(xterm);
    focused(document.createElement("textarea"), xterm);
    expect(typingElsewhere()).toBe(false);
  });

  it("is true in any other textarea", () => {
    focused(document.createElement("textarea"));
    expect(typingElsewhere()).toBe(true);
  });

  it("is false on a focused button", () => {
    focused(document.createElement("button"));
    expect(typingElsewhere()).toBe(false);
  });
});
