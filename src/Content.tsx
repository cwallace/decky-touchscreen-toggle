import { ButtonItem, ConfirmModal, Focusable, PanelSection, PanelSectionRow, ToggleField, showModal } from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { installedGames, type Automation, type Game } from "./automation";

export interface Status {
  ok: boolean;
  state: "ready" | "unavailable" | "error";
  enabled?: boolean | null;
  mixed?: boolean;
  message?: string;
  error?: string;
  rollback?: string;
  automation_error?: string;
  unsupported_message?: string;
  devices?: { id: string; name: string; driver: string; inhibited: boolean }[];
  unsupported?: { id: string; name: string; reason: string }[];
}
export type RuleResult = Partial<Status> & { ok: boolean; auto?: boolean; exceptions?: string[] };
export interface TouchApi {
  getStatus(): Promise<Status>;
  setEnabled(enabled: boolean): Promise<Status>;
  getSettings(): Promise<RuleResult>;
  setAutoEnabled(auto: boolean): Promise<RuleResult>;
  setException(appid: string, keep: boolean): Promise<RuleResult>;
  reportGameState(appid: string | null): Promise<RuleResult>;
  releaseAuto(): Promise<RuleResult>;
}
const errorText = (error: unknown): string => error instanceof Error ? error.message : "Decky connection failed.";
const HELP = {
  "Games only": "Automatically disable touch while a game is running and restore touch when it exits. Outside games, or if game detection is unknown or lost, touch stays enabled. Game exceptions take precedence. Turn this off to use the manual switch.",
  "Game exceptions": "Select installed games that should keep touch enabled during gameplay. Exceptions take precedence over Games only. Deselect a game to remove its exception.",
};
function Help({ title }: { title: keyof typeof HELP }) {
  const opened = useRef(false);
  const open = (event: { stopPropagation(): void; preventDefault(): void }) => {
    event.stopPropagation(); event.preventDefault();
    if (opened.current) return;
    opened.current = true;
    showModal(<ConfirmModal strTitle={title} strDescription={HELP[title]} strOKButtonText="Got it" bAlertDialog />, undefined,
      { fnOnClose: () => { opened.current = false; } });
  };
  return <Focusable role="button" tabIndex={0} aria-label={`About ${title}`} title={`About ${title}`}
    onActivate={open} onClick={open}
    onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") open(event); }}
    onKeyUp={(event) => { if (event.key === "Enter" || event.key === " ") event.stopPropagation(); }}
    style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: "50%", border: "1px solid currentColor", fontSize: 13, cursor: "pointer", flexShrink: 0 }}
  >?</Focusable>;
}
function Heading({ title }: { title: keyof typeof HELP }) {
  return <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}><span>{title}</span><Help title={title} /></span>;
}

export function Content({ api, monitor, catalog = installedGames }: { api: TouchApi; monitor?: Automation; catalog?: () => Game[] }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [rules, setRules] = useState<{ auto: boolean; exceptions: string[] } | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [monitorError, setMonitorError] = useState("");
  const [games, setGames] = useState<Game[]>([]);
  const [catalogError, setCatalogError] = useState("");
  const [limit, setLimit] = useState(50);
  const pending = useRef(false);
  const mounted = useRef(false);
  const adoptRules = (result: RuleResult) => {
    if (typeof result.auto === "boolean") setRules((prior) => ({ auto: result.auto!, exceptions: result.exceptions || prior?.exceptions || [] }));
  };
  const refresh = useCallback(async () => {
    if (pending.current) return;
    pending.current = true;
    if (mounted.current) setBusy(true);
    try {
      const [result, settings] = await Promise.all([api.getStatus(), api.getSettings()]);
      if (!mounted.current) return;
      setStatus(result); adoptRules(settings);
      setError(!result.ok ? result.error || "Touchscreen status is unavailable." : !settings.ok ? settings.error || "Game rules are unavailable." : "");
      try { setGames(catalog()); setCatalogError(""); }
      catch (e) { setGames([]); setCatalogError(errorText(e)); }
    } catch (e) {
      if (mounted.current) { setStatus(null); setError(errorText(e)); }
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }, [api, catalog]);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    const visible = () => { if (document.visibilityState !== "hidden") void refresh(); };
    window.addEventListener("focus", visible);
    document.addEventListener("visibilitychange", visible);
    // The lifetime worker broadcasts verified changes even when Content is not
    // mounted. Closing this panel never disposes the worker or releases auto.
    const update = () => {
      const snapshot = monitor?.snapshot();
      if (!snapshot || !mounted.current || pending.current) return;
      setMonitorError(snapshot.error);
      if (snapshot.status) setStatus(snapshot.status);
    };
    const unsubscribe = monitor?.subscribe(update);
    update();
    return () => {
      mounted.current = false;
      unsubscribe?.();
      window.removeEventListener("focus", visible);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [refresh, monitor]);

  const change = async (operation: () => Promise<RuleResult>) => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {
      const result = await operation();
      if (!mounted.current) return;
      adoptRules(result);
      if (result.ok && result.state) setStatus(result as Status);
      if (!result.ok) {
        setError((result.error || result.message || "Touchscreen change failed.") + (result.rollback ? ` Rollback: ${result.rollback}.` : ""));
        // Failed mutation/rollback may have changed hardware. Read, never infer.
        try { const actual = await api.getStatus(); if (mounted.current) setStatus(actual); }
        catch { if (mounted.current) setStatus(null); }
      }
    } catch (e) {
      if (mounted.current) { setStatus(null); setError(errorText(e)); }
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
      monitor?.reconcile();
    }
  };
  const selected = rules?.exceptions || [];
  const errors = [...new Set([error, status?.automation_error, monitorError].filter(Boolean))].join(" ");
  return <PanelSection title="Touchscreen">
    <PanelSectionRow>
      <ToggleField label="Disable touchscreen" checked={status?.enabled === false && status?.mixed !== true}
        disabled={busy || !rules || rules.auto || status?.state !== "ready" || !status.ok}
        onChange={(checked) => { void change(() => api.setEnabled(!checked)); }} />
    </PanelSectionRow>
    <PanelSectionRow>
      <div role="group" aria-label="Touchscreen status" style={{ paddingTop: 12, paddingBottom: 8, width: "100%" }}>
        <div aria-live="polite" role="status">{busy ? "Checking touchscreen state…" : status?.message}</div>
        {rules?.auto && <div style={{ marginTop: 12, lineHeight: 1.4 }}>Games only is on, so manual control is unavailable. Touch is disabled automatically when a game is detected, except for games in your exception list.</div>}
        {errors && <div role="alert" style={{ color: "#ffb5b5", marginTop: 8 }}>{errors}</div>}
        {status?.unsupported_message && <div style={{ marginTop: 8 }}>{status.unsupported_message}</div>}
      </div>
    </PanelSectionRow>
    <PanelSectionRow>
      <div role="group" aria-label="Automatic control" style={{ paddingTop: 24, width: "100%" }}>
        <ToggleField label={<Heading title="Games only" />} checked={rules?.auto === true} disabled={busy || !rules}
          onChange={(auto) => { void change(() => api.setAutoEnabled(auto)); }} />
      </div>
    </PanelSectionRow>
    <PanelSectionRow>
      <div role="group" aria-label="Game exceptions heading" style={{ paddingTop: 32, paddingBottom: 12 }}>
        <Heading title="Game exceptions" />
      </div>
    </PanelSectionRow>
    {catalogError && <PanelSectionRow>{catalogError}</PanelSectionRow>}
    {games.slice(0, limit).map((game) => <PanelSectionRow key={game.appid}>
      <ToggleField label={game.name} checked={selected.includes(game.appid)} disabled={busy || !rules}
        onChange={(keep) => { void change(() => api.setException(game.appid, keep)); }} />
    </PanelSectionRow>)}
    {!games.length && <PanelSectionRow>No installed games found.</PanelSectionRow>}
    {games.length > limit && <PanelSectionRow><ButtonItem onClick={() => setLimit((n) => n + 50)}>Show more games</ButtonItem></PanelSectionRow>}
  </PanelSection>;
}
