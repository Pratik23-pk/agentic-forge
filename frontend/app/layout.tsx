import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Agentic Forge",
    template: "%s · Agentic Forge",
  },
  description: "Plan, build, validate and preview complete software from a single prompt.",
};

export const viewport: Viewport = {
  themeColor: "#0e0f11",
  colorScheme: "dark",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={cn("dark h-full", GeistSans.variable, GeistMono.variable)}>
      <body className="min-h-full">
        <TooltipProvider delayDuration={400} skipDelayDuration={300}>
          {children}
        </TooltipProvider>
        <Toaster />
      </body>
    </html>
  );
}
