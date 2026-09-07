import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import {
  DEFAULT_FONT_SCALE,
  DEFAULT_WIDTH,
  MAX_WIDTH,
  MIN_WIDTH,
  STORAGE_KEY_WIDTH,
  useChatPreferences,
} from "../useChatPreferences";

describe("useChatPreferences", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useRealTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("defaults width to 480 when localStorage is empty", () => {
    const { result } = renderHook(() => useChatPreferences());
    expect(result.current.width).toBe(DEFAULT_WIDTH);
    expect(result.current.width).toBe(480);
  });

  it('restores a stored width of "600"', async () => {
    localStorage.setItem(STORAGE_KEY_WIDTH, "600");
    const { result } = renderHook(() => useChatPreferences());
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.width).toBe(600);
  });

  it("falls back to default for invalid stored values: -1, 9999, abc", async () => {
    for (const bad of ["-1", "9999", "abc"]) {
      localStorage.setItem(STORAGE_KEY_WIDTH, bad);
      const { result } = renderHook(() => useChatPreferences());
      await act(async () => {
        await Promise.resolve();
      });
      expect(result.current.width).toBe(DEFAULT_WIDTH);
      localStorage.clear();
    }
  });

  it("clamps setWidth to [MIN_WIDTH, MAX_WIDTH]", () => {
    const { result } = renderHook(() => useChatPreferences());
    act(() => {
      result.current.setWidth(100);
    });
    expect(result.current.width).toBe(MIN_WIDTH);
    act(() => {
      result.current.setWidth(9000);
    });
    expect(result.current.width).toBe(MAX_WIDTH);
    act(() => {
      result.current.setWidth(540);
    });
    expect(result.current.width).toBe(540);
  });

  it("debounces localStorage write 250ms after setWidth(540)", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useChatPreferences());
    act(() => {
      result.current.setWidth(540);
    });
    expect(localStorage.getItem(STORAGE_KEY_WIDTH)).toBeNull();
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(localStorage.getItem(STORAGE_KEY_WIDTH)).toBeNull();
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(localStorage.getItem(STORAGE_KEY_WIDTH)).toBe("540");
  });

  it("clears pending debounce timer on unmount", () => {
    vi.useFakeTimers();
    const { result, unmount } = renderHook(() => useChatPreferences());
    act(() => {
      result.current.setWidth(540);
    });
    unmount();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(localStorage.getItem(STORAGE_KEY_WIDTH)).toBeNull();
  });

  it("exposes fontScale === 1 by default and setFontScale as a function", () => {
    const { result } = renderHook(() => useChatPreferences());
    expect(result.current.fontScale).toBe(DEFAULT_FONT_SCALE);
    expect(result.current.fontScale).toBe(1);
    expect(typeof result.current.setFontScale).toBe("function");
    act(() => {
      result.current.setFontScale(1.25);
    });
  });
});
