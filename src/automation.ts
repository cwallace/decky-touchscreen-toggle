import type { Status, TouchApi } from "./Content";

export const HEARTBEAT_MS = 3000;
export const RPC_WARNING_MS = 8000;
export interface Game { appid: string; name: string }
interface Overview {
  appid: number;
  app_type: number;
  display_name?: string;
  local_per_client_data?: { installed?: boolean };
}
interface Lifetime { unAppID: number; nInstanceID: number; bRunning: boolean }
interface SteamHost {
  SteamUIStore?: { MainRunningApp?: Overview; MainRunningAppID?: number };
  appStore?: { allApps?: Overview[] };
  SteamClient?: { GameSessions?: { RegisterForAppLifetimeNotifications?: (fn: (event: Lifetime) => void) => { unregister(): void } } };
}
const hostWindow = (): SteamHost => window as unknown as SteamHost;
// Steam's EAppType values: Game, Demo, Shortcut. No signed bitwise coercion.
const isGame = (type: number): boolean => [1, 8, 1073741824].includes(type);
function appId(value: number): string {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error("Invalid Steam app ID; touch remains enabled.");
  return String(value);
}
export function installedGames(host = hostWindow()): Game[] {
  const apps = host.appStore?.allApps;
  if (!Array.isArray(apps)) throw new Error("Installed game catalog is unavailable.");
  const games = new Map<string, Game>();
  for (const app of apps) {
    if (!isGame(app.app_type) || app.local_per_client_data?.installed !== true) continue;
    const id = appId(app.appid);
    games.set(id, { appid: id, name: app.display_name || `App ${id}` });
  }
  return [...games.values()].sort((a, b) => a.name.localeCompare(b.name));
}
export interface GameSource {
  current(): string | null;
  subscribe(notify: () => void): () => void;
}
export function steamSource(host = hostWindow()): GameSource {
  // Exit events can precede store reconciliation. Tombstones prevent an old
  // MainRunningApp getter from re-inhibiting touch until a new start is seen.
  const exited = new Set<string>();
  return {
    current() {
      const store = host.SteamUIStore;
      if (!store || !("MainRunningApp" in store) || !("MainRunningAppID" in store)) {
        throw new Error("Steam game detection is unavailable; touch remains enabled.");
      }
      const overview = store.MainRunningApp;
      const id = store.MainRunningAppID;
      if (overview === undefined && id === undefined) return null;
      if (!overview || id !== overview.appid) throw new Error("Steam game state is uncertain; touch remains enabled.");
      const exact = appId(id);
      return isGame(overview.app_type) && !exited.has(exact) ? exact : null;
    },
    subscribe(notify) {
      const sessions = host.SteamClient?.GameSessions;
      if (!sessions?.RegisterForAppLifetimeNotifications) return () => {};
      const registration = sessions.RegisterForAppLifetimeNotifications((event) => {
        try {
          const id = appId(event.unAppID);
          if (event.bRunning === true) exited.delete(id);
          else if (event.bRunning === false) exited.add(id);
        } catch { /* Unknown event: the authoritative snapshot still fails open. */ }
        notify();
      });
      return () => registration.unregister();
    },
  };
}
export interface AutomationSnapshot { status?: Status; error: string }
export interface Automation {
  reconcile(): void;
  snapshot(): AutomationSnapshot;
  subscribe(fn: () => void): () => void;
  dispose(): Promise<void>;
}
const message = (e: unknown): string => e instanceof Error ? e.message : "Decky connection failed.";

/** One plugin-lifetime worker, independent of the quick-access Content mount. */
export function createAutomation(
  api: Pick<TouchApi, "reportGameState" | "releaseAuto">,
  source = steamSource(),
): Automation {
  let stopped = false;
  let dirty = false;
  let flight: Promise<void> | undefined;
  let disposal: Promise<void> | undefined;
  let state: AutomationSnapshot = { error: "" };
  const listeners = new Set<() => void>();
  const publish = (next: AutomationSnapshot) => {
    state = next;
    for (const listener of listeners) listener();
  };
  async function drain() {
    // Coalesce event storms; at most two reports per drain. A hung RPC holds the
    // single flight (no overlapping retry); backend lease then restores touch.
    for (let pass = 0; pass < 2 && dirty && !stopped; pass++) {
      dirty = false;
      let game: string | null = null;
      let detectionError = "";
      try { game = source.current(); } catch (e) { detectionError = message(e); }
      const warning = setTimeout(() => {
        if (!stopped) publish({ error: "Game monitoring response timed out; heartbeat lease will restore touch." });
      }, RPC_WARNING_MS);
      try {
        const result = await api.reportGameState(game);
        if (!stopped) publish({
          status: result.state ? result as Status : undefined,
          error: !result.ok ? result.error || "Automatic touchscreen change failed." : detectionError,
        });
      } catch (e) {
        if (!stopped) publish({ error: message(e) });
      } finally { clearTimeout(warning); }
    }
  }
  function reconcile() {
    if (stopped) return;
    dirty = true;
    if (!flight) flight = drain().finally(() => { flight = undefined; });
  }
  let unregister: () => void = () => {};
  try { unregister = source.subscribe(reconcile); } catch { /* Polling remains available. */ }
  const timer = setInterval(reconcile, HEARTBEAT_MS);
  reconcile();
  return {
    reconcile,
    snapshot: () => state,
    subscribe(fn) { listeners.add(fn); return () => { listeners.delete(fn); }; },
    dispose() {
      if (disposal) return disposal;
      stopped = true;
      clearInterval(timer);
      try { unregister(); } catch { /* Still release the backend lease. */ }
      listeners.clear();
      disposal = (async () => {
        // Bound teardown even if the connection never resolves. release_auto is
        // queued after the prior report; backend serialization handles in-flight IO.
        let timeout: ReturnType<typeof setTimeout> | undefined;
        try {
          await Promise.race([flight, new Promise<void>((resolve) => { timeout = setTimeout(resolve, RPC_WARNING_MS); })]);
        } finally { clearTimeout(timeout); }
        try {
          const result = await api.releaseAuto();
          if (!result.ok) {
            const error = result.error || "Automatic touchscreen restoration failed.";
            publish({ error });
            console.error("[Touchscreen Toggle] Frontend release:", error);
          }
        } catch (e) {
          publish({ error: message(e) });
          console.error("[Touchscreen Toggle] Frontend release:", message(e));
        }
      })();
      return disposal;
    },
  };
}
