import type { Metadata } from "next";
import { PriceWatchPage } from "@/components/run/PriceWatchPage";

export const metadata: Metadata = { title: "Price watch · CategoryOS" };

export default function Page() {
  return <PriceWatchPage />;
}
