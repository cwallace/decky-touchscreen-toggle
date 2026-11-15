import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
vi.mock("@decky/ui", () => ({
  PanelSection: ({ children }: { children: ReactNode }) => (
    <section>{children}</section>
  ),
  PanelSectionRow: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  ToggleField: ({ label, checked, disabled, onChange }: any) => (
    <button
      role="switch"
      aria-label={label}
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      {label}
    </button>
  ),
  ButtonItem: ({ children, onClick, disabled }: any) => (
    <button onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
}));
import { Content, type Status, type TouchApi } from "../src/Content";
afterEach(cleanup);
const ready = (enabled = true, extra = {}): Status => ({
  ok: true,
  state: "ready",
  enabled,
  mixed: false,
  message: enabled ? "All touchscreens enabled." : "All touchscreens disabled.",
  devices: [],
  unsupported: [],
  ...extra,
});
const api = (status: Status = ready()): TouchApi => ({
  getStatus: vi.fn(async () => status),
  setEnabled: vi.fn(async (enabled) => ready(enabled)),
});
const switchEl = () => screen.getByRole("switch") as HTMLButtonElement;
const checked = () => switchEl().getAttribute("aria-checked");

describe("single global touchscreen switch", () => {
  it("labels the switch as disabling touch", async () => {
    render(<Content api={api()} />);
    await screen.findByText("All touchscreens enabled.");
    expect(
      screen.getByRole("switch", { name: "Disable touchscreen" }),
    ).toBeTruthy();
  });
  it("starts off and disabled while status is unknown", async () => {
    const bridge = api();
    bridge.getStatus = vi.fn(() => new Promise(() => {}));
    render(<Content api={bridge} />);
    expect(switchEl().disabled).toBe(true);
    expect(checked()).toBe("false");
    expect(screen.getByText("Checking touchscreen state…")).toBeTruthy();
    expect(bridge.setEnabled).not.toHaveBeenCalled();
  });
  it("is off while touchscreens are enabled and disables them when switched on", async () => {
    const bridge = api();
    render(<Content api={bridge} />);
    await screen.findByText("All touchscreens enabled.");
    expect(screen.getAllByRole("switch")).toHaveLength(1);
    expect(checked()).toBe("false");
    expect(screen.queryByRole("button", { name: "Refresh state" })).toBeNull();
    fireEvent.click(switchEl());
    await waitFor(() =>
      expect(bridge.setEnabled).toHaveBeenCalledExactlyOnceWith(false),
    );
    await waitFor(() => expect(checked()).toBe("true"));
    expect(screen.getByText("All touchscreens disabled.")).toBeTruthy();
  });
  it("is on while touchscreens are disabled and re-enables them when switched off", async () => {
    const bridge = api(ready(false));
    render(<Content api={bridge} />);
    await screen.findByText("All touchscreens disabled.");
    expect(checked()).toBe("true");
    fireEvent.click(switchEl());
    await waitFor(() =>
      expect(bridge.setEnabled).toHaveBeenCalledExactlyOnceWith(true),
    );
    await waitFor(() => expect(checked()).toBe("false"));
    expect(screen.getByText("All touchscreens enabled.")).toBeTruthy();
  });
  it("does not optimistically show success before verified reply", async () => {
    const bridge = api();
    let resolve!: (s: Status) => void;
    bridge.setEnabled = vi.fn(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    render(<Content api={bridge} />);
    await screen.findByText("All touchscreens enabled.");
    fireEvent.click(switchEl());
    expect(checked()).toBe("false");
    expect(switchEl().disabled).toBe(true);
    resolve(ready(false));
    await screen.findByText("All touchscreens disabled.");
    expect(checked()).toBe("true");
  });
  it("reports mixed state honestly", async () => {
    render(
      <Content
        api={api(
          ready(false, { mixed: true, message: "Some touchscreens disabled." }),
        )}
      />,
    );
    await screen.findByText("Some touchscreens disabled.");
    expect(checked()).toBe("false");
  });
  it("discloses unsupported hardware", async () => {
    render(
      <Content
        api={api(
          ready(true, {
            unsupported_message: "One touchscreen cannot be controlled.",
          }),
        )}
      />,
    );
    await screen.findByText("One touchscreen cannot be controlled.");
  });
  it("does not enable a switch with no supported hardware", async () => {
    render(
      <Content
        api={api({
          ok: true,
          state: "unavailable",
          enabled: null,
          message: "No supported physical touchscreen detected.",
        })}
      />,
    );
    await screen.findByText("No supported physical touchscreen detected.");
    expect(switchEl().disabled).toBe(true);
    expect(checked()).toBe("false");
  });
  it("shows authorization failure and rollback without claiming success", async () => {
    const bridge = api();
    bridge.setEnabled = vi.fn(async () => ({
      ok: false,
      state: "error",
      error: "Passwordless sudo unavailable",
      rollback: "incomplete",
    }));
    render(<Content api={bridge} />);
    await screen.findByText("All touchscreens enabled.");
    fireEvent.click(switchEl());
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "Passwordless sudo unavailable",
      ),
    );
    expect(screen.getByRole("alert").textContent).toContain("incomplete");
    expect(screen.queryByText("All touchscreens disabled.")).toBeNull();
    expect(checked()).toBe("false");
  });
  it("keeps the switch on when re-enabling fails", async () => {
    const bridge = api(ready(false));
    bridge.setEnabled = vi.fn(async () => ({
      ok: false,
      state: "error",
      error: "Passwordless sudo unavailable",
    }));
    render(<Content api={bridge} />);
    await screen.findByText("All touchscreens disabled.");
    fireEvent.click(switchEl());
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "Passwordless sudo unavailable",
      ),
    );
    expect(checked()).toBe("true");
    expect(screen.queryByText("All touchscreens enabled.")).toBeNull();
  });
  it("recovers from a bridge error automatically on reopening", async () => {
    const bridge = api();
    bridge.getStatus = vi
      .fn()
      .mockRejectedValueOnce(new Error("Decky disconnected"))
      .mockResolvedValue(ready());
    const panel = render(<Content api={bridge} />);
    await screen.findByRole("alert");
    expect(switchEl().disabled).toBe(true);
    panel.unmount();
    render(<Content api={bridge} />);
    await screen.findByText("All touchscreens enabled.");
    expect(bridge.getStatus).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("reads changed hardware state on each panel mount", async () => {
    const bridge = api();
    bridge.getStatus = vi
      .fn()
      .mockResolvedValueOnce(ready())
      .mockResolvedValueOnce(ready(false));
    const panel = render(<Content api={bridge} />);
    await screen.findByText("All touchscreens enabled.");
    expect(checked()).toBe("false");
    panel.unmount();
    render(<Content api={bridge} />);
    await screen.findByText("All touchscreens disabled.");
    expect(bridge.getStatus).toHaveBeenCalledTimes(2);
    expect(checked()).toBe("true");
    expect(bridge.setEnabled).not.toHaveBeenCalled();
  });
  it("does not poll or make touch changes while the panel remains open", async () => {
    vi.useFakeTimers();
    try {
      const bridge = api();
      render(<Content api={bridge} />);
      await act(async () => {
        await Promise.resolve();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15000);
      });
      expect(bridge.getStatus).toHaveBeenCalledTimes(1);
      expect(bridge.setEnabled).not.toHaveBeenCalled();
    } finally {
      cleanup();
      vi.useRealTimers();
    }
  });
  it("does not render the removed explanatory paragraph", async () => {
    render(<Content api={api()} />);
    await screen.findByText("All touchscreens enabled.");
    expect(
      screen.queryByText(/Controls all supported physical touchscreens/),
    ).toBeNull();
    expect(screen.queryByText(/Reboot restores touch/)).toBeNull();
    expect(screen.queryByText(/forced plugin stop/)).toBeNull();
  });
});
