import type { Metadata } from "next";
import { InventoryHealthPage } from "@/components/run/InventoryHealthPage";

export const metadata: Metadata = { title: "Inventory health · CategoryOS" };

export default function Page() {
  return <InventoryHealthPage />;
}
