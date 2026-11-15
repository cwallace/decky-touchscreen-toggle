import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";

export interface Status {
  ok: boolean;
  state: "ready" | "unavailable" | "error";
  enabled?: boolean | null;
  mixed?: boolean;
  message?: string;
  error?: string;
  rollback?: string;
  unsupported_message?: string;
  devices?: { id: string; name: string; driver: string; inhibited: boolean }[];
  unsupported?: { id: string; name: string; reason: string }[];
}
export interface TouchApi {
  getStatus: () => Promise<Status>;
  setEnabled: (enabled: boolean) => Promise<Status>;
}
const errorText = (error: unknown): string =>
  error instanceof Error ? error.message : "Decky connection failed.";

export function Content({ api }: { api: TouchApi }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const mounted = useRef(false);
  const refresh = useCallback(async () => {
    if (pending.current) return;
    pending.current = true;
    if (mounted.current) setBusy(true);
    try {
      const result = await api.getStatus();
      if (mounted.current) {
        setStatus(result);
        setError(
          result.ok
            ? ""
            : result.error ||
                result.message ||
                "Touchscreen status is unavailable.",
        );
      }
    } catch (e) {
      if (mounted.current) {
        setStatus(null);
        setError(errorText(e));
      }
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }, [api]);

  useEffect(() => {
    mounted.current = true;
    // Decky mounts non-alwaysRender plugin content when its panel is visible.
    // Read once on each opening; toggles use the backend's verified response.
    void refresh();
    return () => {
      mounted.current = false;
    };
  }, [refresh]);

  const change = async (enabled: boolean) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api.setEnabled(enabled);
      if (!mounted.current) return;
      // Only adopt a verified reply; a failed change must not claim the new state.
      if (result.ok) setStatus(result);
      if (!result.ok) {
        const message =
          result.error || result.message || "Touchscreen change failed.";
        setError(
          message + (result.rollback ? ` Rollback: ${result.rollback}.` : ""),
        );
      }
    } catch (e) {
      if (mounted.current) {
        setStatus(null);
        setError(errorText(e));
      }
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  return (
    <PanelSection title="Touchscreen">
      <PanelSectionRow>
        <ToggleField
          label="Disable touchscreen"
          checked={status?.enabled === false && status?.mixed !== true}
          disabled={busy || status?.state !== "ready" || !status.ok}
          onChange={(checked) => {
            void change(!checked);
          }}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <div aria-live="polite" role="status">
          {busy ? "Checking touchscreen state…" : status?.message}
        </div>
        {error && (
          <div role="alert" style={{ color: "#ffb5b5", marginTop: 8 }}>
            {error}
          </div>
        )}
        {status?.unsupported_message && (
          <div style={{ marginTop: 8 }}>{status.unsupported_message}</div>
        )}
      </PanelSectionRow>
    </PanelSection>
  );
}
