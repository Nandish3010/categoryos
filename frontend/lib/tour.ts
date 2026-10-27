/** The judges' guided tour: steps, and the "already seen" flag (localStorage, never trusted to exist). */

export const TOUR_STORAGE_KEY = "categoryos.tour.v1";
export const TOUR_EVENT = "categoryos:tour";

export type MeeraPose = "waving" | "pointing" | "thinking" | "celebrating";

export type TourStep = {
  id: string;
  title: string;
  body: string;
  /** Where this step lives. Moving to the step navigates here. */
  href: string;
  pose: MeeraPose;
};

export const TOUR_STEPS: TourStep[] = [
  {
    id: "board",
    title: "Hi, I'm Meera. Start on the board",
    body: "Four vendor applications are waiting for a decision. Each card leads with the verdict counts and the rupees at risk. V001 is the one to open first.",
    href: "/",
    pose: "waving",
  },
  {
    id: "decision",
    title: "V001: the decision and the margin lever",
    body: "The recommendation sits on top. Drag the target-margin slider: SKUs flip between list, negotiate and reject, and the capital at risk updates live.",
    href: "/vendors/V001",
    pose: "pointing",
  },
  {
    id: "verifier",
    title: "The verifier: caught, then corrected",
    body: "Every number the agents write is checked against the data. Open the verifier panel and find a claim that was caught as wrong, then the corrected one that replaced it.",
    href: "/vendors/V001",
    pose: "pointing",
  },
  {
    id: "negotiate",
    title: "V002: negotiating with a deal evaluator",
    body: "Use the deal evaluator or the live call. A conditional offer is rejected when it costs more than 0.1%, and the app shows counter-offers that keep the margin.",
    href: "/vendors/V002?stage=negotiate",
    pose: "pointing",
  },
  {
    id: "mis",
    title: "Run inbox: the Category MIS",
    body: "After onboarding, the Run area is the daily desk: the Category MIS, PO tracker, catalog fixes, promotions and price watch, all from the same verified data.",
    href: "/run",
    pose: "pointing",
  },
  {
    id: "impact",
    title: "The impact meter",
    body: "Back on the board, the impact meter shows the review time saved against doing this by hand. That is the whole loop. Thanks for looking!",
    href: "/",
    pose: "celebrating",
  },
];

export function readTourSeen(): boolean {
  try {
    return window.localStorage.getItem(TOUR_STORAGE_KEY) === "done";
  } catch {
    return false; // storage blocked: treat as unseen, but never throw
  }
}

export function markTourSeen(): void {
  try {
    window.localStorage.setItem(TOUR_STORAGE_KEY, "done");
  } catch {
    /* storage blocked: the tour may offer itself again next visit */
  }
}

export function clampStep(i: number): number {
  return Math.min(Math.max(Math.trunc(i), 0), TOUR_STEPS.length - 1);
}

/** Ask the mounted tour to open at the first step (from any "Take the tour" link). */
export function startTour(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(TOUR_EVENT));
}

/** Only auto-open on a wide screen, on the board, for a first-time visitor. */
export function shouldAutoStart(pathname: string, width: number, seen: boolean): boolean {
  return !seen && pathname === "/" && width >= 900;
}
