import { Suspense } from "react";
import { Workspace } from "@/components/workspace/Workspace";

async function Resolved({ params }: { params: PageProps<"/vendors/[id]">["params"] }) {
  const { id } = await params;
  return <Workspace key={id} vendorId={id} />;
}

export default function Page(props: PageProps<"/vendors/[id]">) {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-text-dim">Loading workspace&hellip;</div>}>
      <Resolved params={props.params} />
    </Suspense>
  );
}
