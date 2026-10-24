"use client";

import { useCallback, useSyncExternalStore } from "react";

type Kind = "local" | "session";
const EVENT = "dl-storage";

function store(kind: Kind): Storage | null {
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null; // private mode / storage disabled
  }
}

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(EVENT, callback);
  };
}

/**
 * A value remembered in browser storage. The server render (and the first client render)
 * use `fallback`, then the stored value, so hydration never mismatches.
 */
export function useStoredValue(key: string, fallback: string | null, kind: Kind = "local") {
  const value = useSyncExternalStore(
    subscribe,
    () => store(kind)?.getItem(key) ?? fallback,
    () => fallback,
  );
  const setValue = useCallback(
    (next: string | null) => {
      const s = store(kind);
      try {
        if (next === null) s?.removeItem(key);
        else s?.setItem(key, next);
      } catch {
        // quota or storage disabled: the value just isn't remembered
      }
      window.dispatchEvent(new Event(EVENT));
    },
    [key, kind],
  );
  return [value, setValue] as const;
}
