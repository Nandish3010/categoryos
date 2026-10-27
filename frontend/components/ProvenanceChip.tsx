import { History } from "lucide-react";
import { provenanceLabel, type Provenance } from "@/lib/provenance";
import { Tag } from "./Chip";

/** "Replay of live run · recorded <date> · $X" or "Replay of scripted run". Renders nothing outside replay mode. */
export function ProvenanceChip({ provenance }: { provenance: Provenance | null | undefined }) {
  const label = provenanceLabel(provenance);
  if (!label) return null;
  return (
    <Tag tone={provenance?.source === "live" ? "accent" : "neutral"} title="Where this recorded run came from">
      <History size={16} aria-hidden="true" />
      <span data-testid="provenance">{label}</span>
    </Tag>
  );
}
