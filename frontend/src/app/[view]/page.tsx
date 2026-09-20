import { notFound } from "next/navigation";
import { Dashboard, type View } from "@/components/dashboard";
export function generateStaticParams() {
  return ["home", "team", "market", "ask"].map((view) => ({ view }));
}
export default async function Page({
  params,
}: {
  params: Promise<{ view: string }>;
}) {
  const { view } = await params;
  if (!["home", "team", "market", "ask"].includes(view)) notFound();
  return <Dashboard view={view as View} />;
}
