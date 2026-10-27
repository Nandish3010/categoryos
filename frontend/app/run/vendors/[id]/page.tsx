import type { Metadata } from "next";
import { Suspense } from "react";
import { VendorReviewPage } from "@/components/run/VendorReviewPage";

export const metadata: Metadata = { title: "Vendor review · CategoryOS" };

async function Resolved({ params }: { params: PageProps<"/run/vendors/[id]">["params"] }) {
  const { id } = await params;
  return <VendorReviewPage key={id} vendorId={id} />;
}

export default function Page(props: PageProps<"/run/vendors/[id]">) {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-text-dim">Loading vendor&hellip;</div>}>
      <Resolved params={props.params} />
    </Suspense>
  );
}
