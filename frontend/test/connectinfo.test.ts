// @vitest-environment jsdom
// Remote-connection overlay: the SSH recipe for a loopback-bound server,
// the direct URL when it listens on the network, and the warning that a
// desktop-mode address dies with the process.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  info: {
    hostname: "mbp-15p",
    lan_ip: "192.168.1.42",
    public_host: null as string | null,
    bind_host: "127.0.0.1",
    port: 54321,
    loopback_only: true,
    stable_url: false,
  },
  api: vi.fn(),
}));
vi.mock("../src/state/api", () => ({ api: mocks.api, TOKEN: "abc-def-ghi" }));
vi.mock("../src/state/store", () => ({ activeSession: () => null }));

type ConnectInfo = typeof import("../src/ui/connectinfo");
let connectinfo: ConnectInfo;

const tick = () => new Promise((r) => setTimeout(r, 0));

function commands(): string[] {
  return [...document.querySelectorAll(".connect-cmd code")].map(
    (c) => c.textContent ?? "",
  );
}

async function open(): Promise<void> {
  connectinfo.openConnectInfo();
  await tick(); // the fetch resolves, then the overlay re-renders
  await tick();
}

beforeEach(async () => {
  vi.resetModules();
  document.body.innerHTML = "";
  // location.port is "" under jsdom's default about:blank-ish URL; the
  // component falls back to the protocol default, which is enough to
  // assert the shape of each command.
  mocks.api.mockReset();
  mocks.api.mockImplementation(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(mocks.info) }),
  );
  mocks.info = {
    hostname: "mbp-15p",
    lan_ip: "192.168.1.42",
    public_host: null as string | null,
    bind_host: "127.0.0.1",
    port: 54321,
    loopback_only: true,
    stable_url: false,
  };
  connectinfo = await import("../src/ui/connectinfo");
});

describe("remote connection overlay", () => {
  it("gives the SSH tunnel recipe when the server is loopback-only", async () => {
    await open();
    const [tunnel, connect] = commands();
    // The remote end of the tunnel is the server's own port, not
    // whatever port this client happens to be talking to.
    expect(tunnel).toBe("ssh -N -L 8443:localhost:54321 mbp-15p");
    expect(connect).toBe(
      "terminux --connect http://localhost:8443/?t=abc-def-ghi",
    );
    expect(document.getElementById("connect-overlay")!.hidden).toBe(false);
  });

  it("gives a direct URL, and a warning, when it listens on the network", async () => {
    mocks.info = { ...mocks.info, bind_host: "0.0.0.0", loopback_only: false };
    await open();
    const [connect] = commands();
    expect(connect).toBe(
      "terminux --connect http://192.168.1.42:54321/?t=abc-def-ghi",
    );
    expect(connect).toContain("?t=abc-def-ghi");
    expect(commands()).toHaveLength(1); // no tunnel step
    expect(document.querySelector(".connect-warn")!.textContent).toContain(
      "only thing protecting this port",
    );
  });

  it("falls back to the hostname when no LAN address is known", async () => {
    mocks.info = {
      ...mocks.info,
      bind_host: "0.0.0.0",
      loopback_only: false,
      lan_ip: null,
    };
    await open();
    expect(commands()[0]).toContain("http://mbp-15p:54321/");
  });

  it("names the --public-host in the direct URL and the SSH recipe", async () => {
    mocks.info = {
      ...mocks.info,
      public_host: "macmini.example.com",
      bind_host: "0.0.0.0",
      loopback_only: false,
    };
    await open();
    expect(commands()[0]).toContain("http://macmini.example.com:54321/");
    mocks.info = { ...mocks.info, bind_host: "127.0.0.1", loopback_only: true };
    await open();
    expect(commands()[0]).toBe(
      "ssh -N -L 8443:localhost:54321 macmini.example.com",
    );
  });

  it("warns that a per-session address dies with the process", async () => {
    await open();
    const warnings = [...document.querySelectorAll(".connect-warn")].map(
      (w) => w.textContent ?? "",
    );
    expect(warnings.some((w) => w.includes("until terminux restarts"))).toBe(
      true,
    );
  });

  it("drops the restart warning once the URL is stable", async () => {
    mocks.info = { ...mocks.info, stable_url: true };
    await open();
    expect(document.querySelectorAll(".connect-warn")).toHaveLength(0);
  });

  it("closes on Escape and re-asks the server on the next open", async () => {
    await open();
    window.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", cancelable: true }),
    );
    expect(document.getElementById("connect-overlay")!.hidden).toBe(true);
    await open();
    expect(mocks.api).toHaveBeenCalledTimes(2);
    expect(mocks.api).toHaveBeenCalledWith("/connect-info");
  });
});
