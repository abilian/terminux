// Command bus: one named-handler table shared by every input surface
// (keyboard chords, command palette, native menu). Keeping the
// registry pure (no imports from feature modules) lets it be
// unit-tested in node without dragging in xterm / fetch / window.

type CommandRun = () => void | Promise<void>;

const registry = new Map<string, CommandRun>();

export function register(id: string, run: CommandRun): void {
  if (registry.has(id)) console.warn(`command "${id}" re-registered`);
  registry.set(id, run);
}

export function invoke(id: string): boolean {
  const run = registry.get(id);
  if (!run) {
    console.warn(`command not found: "${id}"`);
    return false;
  }
  void run();
  return true;
}

export function has(id: string): boolean {
  return registry.has(id);
}

// Test-only seam: clear the registry between cases.
export function _reset(): void {
  registry.clear();
}
