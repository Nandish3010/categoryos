import type { Metadata } from "next";
import { CatalogFixesPage } from "@/components/run/CatalogFixesPage";

export const metadata: Metadata = { title: "Catalog fixes · CategoryOS" };

export default function Page() {
  return <CatalogFixesPage />;
}
