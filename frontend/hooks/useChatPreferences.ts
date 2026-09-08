import { useCallback, useEffect, useRef, useState } from "react";

export const MIN_WIDTH = 320;
export const MAX_WIDTH = 720;
export const DEFAULT_WIDTH = 480;
export const DEFAULT_FONT_SCALE = 1;
export const STORAGE_KEY_WIDTH = "nexgen.aiChat.width";
export const DEBOUNCE_MS = 250;

export interface UseChatPreferencesReturn {
  width: number;
  setWidth: (_w: number) => void;
  fontScale: number;
  setFontScale: (_s: number) => void;
}

const clampWidth = (n: number): number => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.floor(n)));

const isValidStoredWidth = (n: number): boolean =>
  Number.isFinite(n) && n >= MIN_WIDTH && n <= MAX_WIDTH;

const readStoredWidth = (): number => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_WIDTH);
    if (raw === null) return DEFAULT_WIDTH;
    const parsed = Number(raw);
    return isValidStoredWidth(parsed) ? parsed : DEFAULT_WIDTH;
  } catch {
    return DEFAULT_WIDTH;
  }
};

/** Single source of truth for AI chat panel layout state.
 *  Reads localStorage on mount; setWidth clamps + debounces a write. */
export function useChatPreferences(): UseChatPreferencesReturn {
  const [width, setWidthState] = useState<number>(DEFAULT_WIDTH);
  const [fontScale, setFontScaleState] = useState<number>(DEFAULT_FONT_SCALE);
  const writeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setWidthState(readStoredWidth());
  }, []);

  useEffect(() => {
    return () => {
      if (writeTimerRef.current !== null) {
        clearTimeout(writeTimerRef.current);
        writeTimerRef.current = null;
      }
    };
  }, []);

  const setWidth = useCallback((next: number) => {
    const clamped = clampWidth(next);
    setWidthState(clamped);
    if (writeTimerRef.current !== null) clearTimeout(writeTimerRef.current);
    writeTimerRef.current = setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY_WIDTH, String(clamped));
      } catch {
        /* quota / private mode */
      }
      writeTimerRef.current = null;
    }, DEBOUNCE_MS);
  }, []);

  const setFontScale = useCallback((next: number) => {
    setFontScaleState(Number.isFinite(next) ? next : DEFAULT_FONT_SCALE);
  }, []);

  return { width, setWidth, fontScale, setFontScale };
}
