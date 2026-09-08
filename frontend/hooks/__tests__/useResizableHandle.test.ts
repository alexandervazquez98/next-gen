import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from "react";
import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useResizableHandle } from "../useResizableHandle";

// PointerEvent is provided by jsdom at runtime; declare a local constructor
// alias to avoid the `no-undef` rule for the global type.
const PE = (
  globalThis as unknown as {
    PointerEvent: new (_type: string, _init?: { clientX?: number }) => Event;
  }
).PointerEvent;

describe("useResizableHandle", () => {
  it("clamps setWidth to MAX_WIDTH (720) when pointermove exceeds MAX_WIDTH", () => {
    const setWidth = vi.fn();
    const { result } = renderHook(() => useResizableHandle(480, setWidth));
    act(() => {
      result.current.onPointerDown({
        clientX: 0,
        preventDefault: () => undefined,
      } as unknown as ReactPointerEvent<HTMLElement>);
    });
    act(() => {
      window.dispatchEvent(new PE("pointermove", { clientX: 1000 }));
    });
    const lastCall = setWidth.mock.calls[setWidth.mock.calls.length - 1][0];
    expect(lastCall).toBe(720);
  });

  it("clamps setWidth to MIN_WIDTH (320) when pointermove goes below MIN_WIDTH", () => {
    const setWidth = vi.fn();
    const { result } = renderHook(() => useResizableHandle(400, setWidth));
    act(() => {
      result.current.onPointerDown({
        clientX: 500,
        preventDefault: () => undefined,
      } as unknown as ReactPointerEvent<HTMLElement>);
    });
    act(() => {
      window.dispatchEvent(new PE("pointermove", { clientX: -1000 }));
    });
    const lastCall = setWidth.mock.calls[setWidth.mock.calls.length - 1][0];
    expect(lastCall).toBe(320);
  });

  it("adds window listeners on pointerdown and removes them on pointerup", () => {
    const addSpy = vi.spyOn(window, "addEventListener");
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const setWidth = vi.fn();
    const { result } = renderHook(() => useResizableHandle(480, setWidth));
    const addBefore = addSpy.mock.calls.length;
    act(() => {
      result.current.onPointerDown({
        clientX: 0,
        preventDefault: () => undefined,
      } as unknown as ReactPointerEvent<HTMLElement>);
    });
    expect(addSpy.mock.calls.length).toBeGreaterThan(addBefore);
    act(() => {
      window.dispatchEvent(new PE("pointerup"));
    });
    expect(removeSpy.mock.calls.length).toBeGreaterThan(addBefore);
  });

  it("does nothing when pointermove fires without a prior pointerdown", () => {
    const setWidth = vi.fn();
    renderHook(() => useResizableHandle(480, setWidth));
    act(() => {
      window.dispatchEvent(new PE("pointermove", { clientX: 1000 }));
    });
    expect(setWidth).not.toHaveBeenCalled();
  });

  it("resets width to 480 on double-click via onDoubleClick", () => {
    const setWidth = vi.fn();
    const { result } = renderHook(() => useResizableHandle(640, setWidth));
    act(() => {
      result.current.onDoubleClick({} as ReactMouseEvent<HTMLElement>);
    });
    expect(setWidth).toHaveBeenCalledWith(480);
  });
});
