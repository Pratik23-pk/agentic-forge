"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

export const SECTIONS = [
  { id: "foundations", label: "Foundations" },
  { id: "primitives", label: "Primitives" },
  { id: "status", label: "Status" },
  { id: "build-stream", label: "Build stream" },
  { id: "code", label: "Code" },
  { id: "preview", label: "Preview" },
  { id: "workspace", label: "Workspace" },
] as const;

/** Section links that follow the reader: the section nearest the top is current. */
export function SectionNav() {
  const [active, setActive] = useState<string>(SECTIONS[0].id);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-80px 0px -60% 0px" },
    );
    for (const section of SECTIONS) {
      const element = document.getElementById(section.id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <nav aria-label="Design system sections" className="flex flex-col gap-0.5">
      {SECTIONS.map((section) => (
        <a
          key={section.id}
          href={`#${section.id}`}
          aria-current={active === section.id ? "location" : undefined}
          className={cn(
            "rounded-md px-2 py-1 text-[13px] transition-colors duration-150",
            active === section.id
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {section.label}
        </a>
      ))}
    </nav>
  );
}
