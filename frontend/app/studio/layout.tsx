import type { Metadata } from "next";

import { StudioProviders } from "@/components/studio/providers";

export const metadata: Metadata = {
  title: "Studio",
};

export default function StudioLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <StudioProviders>{children}</StudioProviders>;
}
