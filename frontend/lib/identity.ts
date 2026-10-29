/** Who the Rules page acts as. A DEMO identity picker, not authentication: anyone can pick anyone. Both values live in
 *  localStorage (never trusted to exist) and are sent as headers on playbook requests. */
export const ACTING_AS_STORAGE = "categoryos.actingAs";
export const VISITOR_STORAGE = "categoryos.visitorId";

function read(key: string): string | null {
  try {
    return globalThis.localStorage?.getItem(key) || null;
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    globalThis.localStorage?.setItem(key, value);
  } catch {
    /* storage blocked: the choice just won't persist */
  }
}

export const getActingAs = () => read(ACTING_AS_STORAGE);
export const setActingAs = (id: string) => write(ACTING_AS_STORAGE, id);

let memoryVisitor: string | null = null;

/** A random id for this browser. On a public deploy it, with the address, names the visitor's private playbook sandbox. */
export function getVisitorId(): string {
  const stored = read(VISITOR_STORAGE);
  if (stored) return stored;
  if (memoryVisitor) return memoryVisitor;
  const raw = globalThis.crypto?.randomUUID?.() ?? `v${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
  memoryVisitor = raw.replace(/[^A-Za-z0-9_-]/g, "");
  write(VISITOR_STORAGE, memoryVisitor);
  return memoryVisitor;
}

export function identityHeaders(): Record<string, string> {
  const h: Record<string, string> = { "X-Visitor-Id": getVisitorId() };
  const acting = getActingAs();
  if (acting) h["X-Acting-As"] = acting;
  return h;
}
