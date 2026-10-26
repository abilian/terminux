// "Show remote connection URL" overlay: the exact commands another
// machine needs to reach this server. The frontend knows its own port
// and token; the backend supplies what it can't see — how the server was
// bound, what this machine is called, and whether the URL outlives the
// run (see GET /api/connect-info).

import { useState } from "preact/hooks";

import { api, TOKEN } from "../state/api";
import { createOverlay, Modal } from "./overlay";

interface ConnectInfo {
  hostname: string;
  lan_ip: string | null;
  public_host: string | null;
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

let info: ConnectInfo | null = null;

const overlay = createOverlay(
  (visible, key) => <ConnectOverlay key={key} visible={visible} info={info} />,
  {
    onClose: () => {
      info = null;
    },
  },
);

export function openConnectInfo(): void {
  overlay.open();
  // Re-fetched per open: the answer changes with the network the
  // machine is on.
  void api("/connect-info")
    .then((r) => (r.ok ? r.json() : null))
    .then((data: ConnectInfo | null) => {
      info = data;
      overlay.rerender();
    })
    .catch(() => {
      info = null;
      overlay.rerender();
    });
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
  const sshHost = data.public_host || data.hostname || "this-machine";
  const directHost = data.public_host ?? data.lan_ip ?? data.hostname;
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
    <Modal
      id="connect-overlay"
      cardId="connect-card"
      visible={shown}
      onClose={overlay.close}
    >
      <div class="connect-header">Connect from another machine</div>
      <div class="connect-body">
        {data ? <Body info={data} /> : <p>Asking the server…</p>}
      </div>
    </Modal>
  );
}
