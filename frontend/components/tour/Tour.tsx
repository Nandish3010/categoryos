"use client";

import { ArrowLeft, ArrowRight, Compass, X } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  TOUR_EVENT,
  TOUR_STEPS,
  clampStep,
  markTourSeen,
  readTourSeen,
  shouldAutoStart,
} from "@/lib/tour";

/**
 * Meera's guided tour: a dismissible, non-modal bubble at the bottom right. It does not block the page, so a judge can
 * poke at the app between steps. Each step names its page; Next navigates there. Mounted once in the root layout, so its
 * state survives route changes.
 */
export function Tour() {
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const nextRef = useRef<HTMLButtonElement | null>(null);

  // First visit: open on the board for wide screens. Storage and viewport are only known after hydration.
  useEffect(() => {
    if (shouldAutoStart(window.location.pathname, window.innerWidth, readTourSeen())) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setOpen(true);
    }
  }, []);

  useEffect(() => {
    const onStart = () => {
      setIndex(0);
      setOpen(true);
      if (window.location.pathname !== TOUR_STEPS[0].href) router.push(TOUR_STEPS[0].href);
    };
    window.addEventListener(TOUR_EVENT, onStart);
    return () => window.removeEventListener(TOUR_EVENT, onStart);
  }, [router]);

  const close = useCallback(() => {
    markTourSeen();
    setOpen(false);
  }, []);

  const go = useCallback(
    (to: number) => {
      const i = clampStep(to);
      setIndex(i);
      const target = TOUR_STEPS[i].href;
      if (target.split("?")[0] !== window.location.pathname || target.includes("?")) router.push(target);
    },
    [router],
  );

  useEffect(() => {
    if (!open) return;
    nextRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, index, close]);

  const step = TOUR_STEPS[index];
  const last = index === TOUR_STEPS.length - 1;
  const here = pathname === step.href.split("?")[0];

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setIndex(0);
          setOpen(true);
          if (window.location.pathname !== "/") router.push("/");
        }}
        className="fixed bottom-4 right-4 z-50 inline-flex min-h-11 items-center gap-2 rounded-card border border-border bg-surface px-3 text-sm text-text-dim hover:bg-surface-2 hover:text-text max-[899px]:bottom-2 max-[899px]:right-2"
      >
        <Compass size={16} aria-hidden="true" />
        Take the tour
      </button>
    );
  }

  return (
    <section
      role="dialog"
      aria-modal="false"
      aria-labelledby="tour-title"
      aria-describedby="tour-body"
      data-testid="tour"
      className="fixed bottom-4 right-4 z-50 flex max-w-[28rem] items-end gap-3 max-[899px]:inset-x-2 max-[899px]:bottom-2 max-[899px]:max-w-none"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        key={step.pose}
        src={`/meera/meera-${step.pose}.png`}
        alt=""
        width={85}
        height={160}
        data-testid="meera"
        className="h-40 w-auto shrink-0 motion-safe:animate-[meera-pop_0.25s_ease-out] max-[899px]:hidden"
      />
      <div className="relative min-w-0 flex-1 rounded-card border border-accent/50 bg-surface p-4 shadow-lg">
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="num text-xs text-text-dim">
            Step {index + 1} of {TOUR_STEPS.length}
          </span>
          <button
            type="button"
            onClick={close}
            aria-label="Skip the tour"
            className="inline-flex h-8 items-center gap-1 rounded-chip px-2 text-xs text-text-dim hover:text-text"
          >
            Skip <X size={16} aria-hidden="true" />
          </button>
        </div>
        <h2 id="tour-title" className="text-base font-semibold">
          {step.title}
        </h2>
        <p id="tour-body" className="mt-1 text-sm text-text-dim">
          {step.body}
        </p>
        {!here ? <p className="mt-1 text-xs text-warn">Next opens the page for this step.</p> : null}
        <div className="mt-3 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => go(index - 1)}
            disabled={index === 0}
            className="inline-flex min-h-11 items-center gap-1 rounded-card border border-border px-3 text-sm disabled:opacity-40"
          >
            <ArrowLeft size={16} aria-hidden="true" /> Back
          </button>
          <button
            ref={nextRef}
            type="button"
            onClick={() => (last ? close() : go(index + 1))}
            className="inline-flex min-h-11 items-center gap-1 rounded-card bg-accent px-4 text-sm font-semibold text-bg"
          >
            {last ? "Done" : "Next"} {last ? null : <ArrowRight size={16} aria-hidden="true" />}
          </button>
        </div>
      </div>
    </section>
  );
}
