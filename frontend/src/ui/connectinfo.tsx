// "Show remote connection URL" overlay: the exact commands another
// machine needs to reach this server. The frontend knows its own port
// and token; the backend supplies what it can't see — how the server was
// bound, what this machine is called, and whether the URL outlives the
// run (see GET /api/connect-info).

import { render } from "preact";
import { useState } from "preact/hooks";

import { api, TOKEN } from "../state/api";
import { activeSession } from "../state/store";

interface ConnectInfo {
  hostname: string;
  lan_ip: string | null;
  bind_host: string;
  // The server's own listening port. Null when the app was built
  // outside the CLI (tests, library use); then our own location is the
  // best available answer.
  port: number | null;
  loopback_only: boolean;
  stable_url: boolean;
}

// Local port suggested for the SSH tunnel; matches the docs' recipe.
const TUNNEL_PORT = 8443;

let host: HTMLDivElement | null = null;
let visible = false;
let info: ConnectInfo | null = null;
let epoch = 0;

function rerender(): void {
  if (host) {
    render(<ConnectOverlay key={epoch} visible={visible} info={info} />, host);
  }
}

function ensure(): void {
  if (!host) {
    host = document.createElement("div");
    // Capture phase: xterm's textarea consumes Escape in its own keydown
    // (same pattern as the keymap and the stats overlay).
    window.addEventListener(
      "keydown",
      (e: KeyboardEvent) => {
        if (visible && e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          closeConnectInfo();
        }
      },
      true,
    );
  }
  if (!host.isConnected) {
    document.body.appendChild(host);
  }
  rerender();
}

export function installConnectInfo(): void {
  ensure();
}

export function openConnectInfo(): void {
  visible = true;
  epoch++; // remount so the card re-grabs focus
  ensure();
  // Re-fetched per open: the answer changes with the network the
  // machine is on.
  void api("/connect-info")
    .then((r) => (r.ok ? r.json() : null))
    .then((data: ConnectInfo | null) => {
      info = data;
      rerender();
    })
    .catch(() => {
      info = null;
      rerender();
    });
}

export function closeConnectInfo(): void {
  visible = false;
  info = null;
  rerender();
  activeSession()?.term.focus();
}

function CopyLine({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div class="connect-cmd">
      <code>{command}</code>
      <button
        type="button"
        class="connect-copy"
        onClick={() => {
          void navigator.clipboard?.writeText(command).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          });
        }}
      >
        {copied ? "copied" : "copy"}
      </button>
    </div>
  );
}

function Body({ info: data }: { info: ConnectInfo }) {
  const port =
    data.port ??
    (location.port || (location.protocol === "https:" ? "443" : "80"));
  const sshHost = data.hostname || "this-machine";
  const directHost = data.lan_ip ?? data.hostname;
  return (
    <>
      {data.loopback_only ? (
        <>
          <p>
            This server listens on <code>{data.bind_host}</code> only, so
            nothing on the network reaches it directly. Forward the port over
            SSH from the other machine:
          </p>
          <CopyLine
            command={`ssh -N -L ${TUNNEL_PORT}:localhost:${port} ${sshHost}`}
          />
          <p>Then, on that same machine:</p>
          <CopyLine
            command={`terminux --connect http://localhost:${TUNNEL_PORT}/?t=${TOKEN}`}
          />
        </>
      ) : (
        <>
          <p>
            This server listens on <code>{data.bind_host}</code>, so any machine
            that can reach it may connect:
          </p>
          <CopyLine
            command={`terminux --connect http://${directHost}:${port}/?t=${TOKEN}`}
          />
          <p class="connect-warn">
            The access code is the only thing protecting this port. Keep it on a
            trusted network, or put SSH or a TLS terminator in front.
          </p>
        </>
      )}
      {!data.stable_url && (
        <p class="connect-warn">
          This address lasts only until terminux restarts: every launch draws a
          new access code, and a new port unless you pass <code>--port</code>.
          Run <code>terminux --server</code> for an address you can bookmark.
        </p>
      )}
    </>
  );
}

interface Props {
  visible: boolean;
  info: ConnectInfo | null;
}

function ConnectOverlay({ visible: shown, info: data }: Props) {
  return (
    <div
      id="connect-overlay"
      hidden={!shown}
      onClick={(e) => {
        // Click on the backdrop (not the card) dismisses.
        if (e.target === e.currentTarget) {
          closeConnectInfo();
        }
      }}
    >
      <div
        id="connect-card"
        // Focusable so Escape lands here, not on the still-focused xterm
        // textarea (which would otherwise feed ESC to the shell).
        tabIndex={-1}
        ref={(el) => {
          if (el && el.dataset.mounted !== "1") {
            el.dataset.mounted = "1";
            el.focus();
          }
        }}
      >
        <div class="connect-header">Connect from another machine</div>
        <div class="connect-body">
          {data ? <Body info={data} /> : <p>Asking the server…</p>}
        </div>
      </div>
    </div>
  );
}
