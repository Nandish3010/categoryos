"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { RUN_NAV } from "@/lib/ops";

const linkCls =
  "inline-flex min-h-11 items-center rounded-card border border-border px-3 text-sm text-text-dim hover:bg-surface-2 hover:text-text";

/** Frame for every Run page: app header (Onboard / Run / Playbook) and the Run sub-navigation. */
export function RunShell({ title, subtitle, right, children }: { title: string; subtitle?: ReactNode; right?: ReactNode; children: ReactNode }) {
  const path = usePathname() ?? "/run";
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6 md:px-6">
      <header className="mb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link href="/" className="text-xl font-semibold tracking-tight">
            CategoryOS
          </Link>
          <nav aria-label="Areas" className="flex items-center gap-2">
            <Link href="/" className={linkCls}>
              Onboard
            </Link>
            <Link href="/run" aria-current="page" className={`${linkCls} border-accent text-text`}>
              Run
            </Link>
            <Link href="/rules" className={linkCls}>
              Playbook
            </Link>
          </nav>
        </div>
        <nav aria-label="Run" className="mt-4 flex flex-wrap items-center gap-1 border-b border-border">
          {RUN_NAV.map((item) => {
            const active = item.match(path);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`-mb-px inline-flex h-10 items-center border-b-2 px-3 text-sm ${
                  active ? "border-accent font-medium text-text" : "border-transparent text-text-dim hover:text-text"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-4 flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {subtitle ? <p className="mt-1 text-sm text-text-dim">{subtitle}</p> : null}
          </div>
          {right}
        </div>
      </header>
      {children}
    </main>
  );
}
