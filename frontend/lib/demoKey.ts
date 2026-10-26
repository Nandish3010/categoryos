/** Live-mode demo key. Lives in sessionStorage only: never env, never NEXT_PUBLIC. */
export const DEMO_KEY_STORAGE = "categoryos.demoKey";

export function getDemoKey(): string | null {
  try {
    return globalThis.sessionStorage?.getItem(DEMO_KEY_STORAGE) || null;
  } catch {
    return null;
  }
}

export function setDemoKey(value: string): void {
  try {
    if (value) globalThis.sessionStorage?.setItem(DEMO_KEY_STORAGE, value);
    else globalThis.sessionStorage?.removeItem(DEMO_KEY_STORAGE);
  } catch {
    /* storage blocked: key just won't persist */
  }
}
