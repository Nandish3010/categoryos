"use client";

import {
  AlertTriangle,
  CheckCheck,
  Cpu,
  Flag,
  OctagonAlert,
  PlayCircle,
  ShieldCheck,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef } from "react";
import type { TraceEvent, TraceEventType } from "@/lib/runs";
import type { SseState } from "@/lib/sse";
import { describeEvent, eventMeta, relTime } from "@/lib/trace";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";
import { TraceItem } from "../TraceItem";

const ICONS: Record<TraceEventType, LucideIcon> = {
  stage_started: PlayCircle,
  tool_call: Wrench,
  model_call: Cpu,
  claim_checked: ShieldCheck,
  stage_result: Flag,
  degraded: AlertTriangle,
  error: OctagonAlert,
  done: CheckCheck,
};

export function TracePanel({
  events,
  conn,
  running,
  hasRun,
}: {
  events: TraceEvent[];
  conn: SseState | "idle";
  running: boolean;
  hasRun: boolean;
}) {
  const ref = useRef<HTMLUListElement>(null);
  const stick = useRef(true);

  // Auto-scroll to the newest event unless the user scrolled up.
  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  const disconnected = conn === "reconnecting";
  return (
    <section aria-label="Agent trace" className="rounded-card border border-border bg-surface">
      <PanelHeader
        title="Agent trace"
        right={
          disconnected ? (
            <span className="text-warn">Disconnected — resuming…</span>
          ) : events.length ? (
            <span className="num">{events.length} events</span>
          ) : null
        }
      />
      <ul
        ref={ref}
        role="log"
        aria-live="off"
        aria-label="Agent activity"
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
        className="max-h-80 min-h-16 overflow-y-auto"
      >
        {events.length === 0 ? (
          running ? (
            <li className="flex flex-col gap-2 p-4" aria-label="Waiting for agent activity">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-4 w-32" />
            </li>
          ) : (
            <TraceItem title={hasRun ? "No activity recorded" : "Run to see agent activity"}>
              Model calls and claim checks stream here once a run starts.
            </TraceItem>
          )
        ) : (
          events.map((ev) => {
            const { title, detail } = describeEvent(ev);
            const Icon = ICONS[ev.type] ?? Cpu;
            return (
              <TraceItem
                key={ev.seq}
                time={relTime(ev.t_rel_ms)}
                title={title}
                icon={<Icon size={16} aria-label={ev.type.replace("_", " ")} role="img" />}
                meta={eventMeta(ev)}
              >
                {detail}
              </TraceItem>
            );
          })
        )}
      </ul>
    </section>
  );
}
