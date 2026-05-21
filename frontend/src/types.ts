// Shapes mirror the backend's AppState.view_json() payload.

export interface TabView {
  id: string;
  title: string;
  user_set_title: boolean;
  live: boolean;
  has_unseen_output: boolean;
  needs_attention: boolean;
}

export interface WorkspaceView {
  id: string;
  name: string;
  tab_ids: string[];
  active_tab_id: string | null;
  // "busy" is the working state — promoted into the idle slot when a
  // foreground task is running and nothing more urgent (unseen/exited)
  // applies. Priority: active > exited > unseen > busy > idle.
  status: "active" | "unseen" | "busy" | "idle" | "exited";
  attention: boolean;
}

export interface StateView {
  workspaces: WorkspaceView[];
  tabs: Record<string, TabView>;
  active_workspace_id: string | null;
  ui: {
    sidebar_width: number;
    sidebar_collapsed: boolean;
    font_size: number;
    copy_on_select: boolean;
    scrollback_persist: boolean;
  };
}

declare global {
  interface Window {
    TERMINUX_TOKEN: string;
  }
}
