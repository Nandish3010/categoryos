import { Tag } from "../Chip";

/** Split a generated text into paragraphs on blank lines. */
export function Paragraphs({ text, className = "" }: { text: string; className?: string }) {
  return (
    <>
      {text
        .split(/\n\s*\n/)
        .map((p) => p.trim())
        .filter(Boolean)
        .map((p, i) => (
          <p key={i} className={`text-sm leading-relaxed ${className}`}>
            {p}
          </p>
        ))}
    </>
  );
}

/** Sentences the verifier struck from a generated text because a number in them did not verify. */
export function StruckNote({ struck }: { struck: string[] }) {
  if (struck.length === 0) return null;
  return (
    <details className="text-xs text-text-dim">
      <summary className="cursor-pointer">
        {struck.length} {struck.length === 1 ? "sentence" : "sentences"} removed because a number in {struck.length === 1 ? "it" : "them"} did not verify
      </summary>
      <ul className="mt-1 list-disc pl-5">
        {struck.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
    </details>
  );
}

export function ModeTags({ mode, degraded }: { mode: string; degraded: boolean }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Tag tone="accent">{mode}</Tag>
      {degraded ? <Tag tone="warn" title="No recorded run was found for this step, so a fixture was served">Fixture served</Tag> : null}
    </span>
  );
}
