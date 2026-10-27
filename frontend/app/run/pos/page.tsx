import type { Metadata } from "next";
import { PoTrackerPage } from "@/components/run/PoTrackerPage";

export const metadata: Metadata = { title: "PO tracker · CategoryOS" };

export default function Page() {
  return <PoTrackerPage />;
}
