import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from "react";
import { useCallback, useEffect, useRef } from "react";

const DEFAULT_MIN_WIDTH = 320;
const DEFAULT_MAX_WIDTH = 720;
const DEFAULT_RESET_WIDTH = 480;

export interface UseResizableHandleOptions {
  minWidth?: number;
  maxWidth?: number;
  resetWidth?: number;
}

export interface ResizableHandleBindings {
  onPointerDown: (_e: ReactPointerEvent<HTMLElement>) => void;
  onDoubleClick: (_e: ReactMouseEvent<HTMLElement>) => void;
}

interface DragState {
  startX: number;
  startW: number;
}

/** Pointer-event plumbing for the chat panel drag handle.
 *  Returns onPointerDown + onDoubleClick; window listeners detach on pointerup
 *  and on consumer unmount. */
export function useResizableHandle(
  width: number,
  setWidth: (_w: number) => void,
  options?: UseResizableHandleOptions,
): ResizableHandleBindings {
  const minWidth = options?.minWidth ?? DEFAULT_MIN_WIDTH;
  const maxWidth = options?.maxWidth ?? DEFAULT_MAX_WIDTH;
  const resetWidth = options?.resetWidth ?? DEFAULT_RESET_WIDTH;

  const dragRef = useRef<DragState | null>(null);
  const listenersRef = useRef<{
    move: (_e: Event) => void;
    up: (_e: Event) => void;
  } | null>(null);

  const detach = useCallback(() => {
    const ls = listenersRef.current;
    if (ls === null) return;
    window.removeEventListener("pointermove", ls.move, true);
    window.removeEventListener("pointerup", ls.up, true);
    listenersRef.current = null;
    dragRef.current = null;
  }, []);

  const onPointerMove = useCallback(
    (e: Event) => {
      const drag = dragRef.current;
      if (drag === null) return;
      const clientX = (e as unknown as { clientX: number }).clientX;
      const delta = clientX - drag.startX;
      const next = Math.min(maxWidth, Math.max(minWidth, Math.floor(drag.startW + delta)));
      setWidth(next);
    },
    [minWidth, maxWidth, setWidth],
  );

  const onPointerUp = useCallback(() => {
    detach();
  }, [detach]);

  useEffect(
    () => () => {
      detach();
    },
    [detach],
  );

  const onPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLElement>) => {
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startW: width };
      const move = (ev: Event) => onPointerMove(ev);
      const up = (_ev: Event) => onPointerUp();
      listenersRef.current = { move, up };
      window.addEventListener("pointermove", move, true);
      window.addEventListener("pointerup", up, true);
    },
    [width, onPointerMove, onPointerUp],
  );

  const onDoubleClick = useCallback(
    (_e: ReactMouseEvent<HTMLElement>) => {
      setWidth(resetWidth);
    },
    [setWidth, resetWidth],
  );

  return { onPointerDown, onDoubleClick };
}
