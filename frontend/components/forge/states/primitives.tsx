"use client";

import {
  ArrowUpRightIcon,
  CopyIcon,
  DownloadIcon,
  FolderGit2Icon,
  GitBranchIcon,
  MonitorIcon,
  MoreHorizontalIcon,
  PlayIcon,
  SmartphoneIcon,
  TabletIcon,
  TrashIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Kbd, KbdGroup } from "@/components/ui/kbd";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Section, Specimen } from "./section";

const STACKS = [
  ["auto", "Detect from prompt"],
  ["nextjs-fullstack", "Next.js full-stack"],
  ["react-fastapi", "React + FastAPI"],
  ["react-node", "React + Express"],
  ["react-vite", "React (Vite)"],
  ["python-cli", "Python CLI"],
] as const;

export function Primitives() {
  return (
    <Section
      id="primitives"
      title="Primitives"
      description="shadcn/ui on Radix, tuned for motion: presses scale to 0.97, popovers grow from their trigger, dialogs stay centred. Primary actions are near-white; ember never fills a button."
    >
      <Specimen label="Buttons">
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap items-center gap-2">
            <Button>
              <PlayIcon data-icon="inline-start" />
              Build
            </Button>
            <Button variant="secondary">Start preview</Button>
            <Button variant="outline">
              <DownloadIcon data-icon="inline-start" />
              Download ZIP
            </Button>
            <Button variant="ghost">Cancel</Button>
            <Button variant="destructive">
              <TrashIcon data-icon="inline-start" />
              Delete
            </Button>
            <Button variant="link">
              View logs
              <ArrowUpRightIcon data-icon="inline-end" />
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm">Small</Button>
            <Button>Default</Button>
            <Button size="lg">Large</Button>
            <Button disabled>
              <Spinner data-icon="inline-start" />
              Building
            </Button>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button size="icon" variant="ghost" aria-label="Copy path">
                  <CopyIcon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Copy path</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button size="icon" variant="ghost" aria-label="Open repository">
                  <FolderGit2Icon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Open repository</TooltipContent>
            </Tooltip>
          </div>
        </div>
      </Specimen>

      <div className="grid gap-10 md:grid-cols-2">
        <Specimen label="Form fields">
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="demo-project">Project name</FieldLabel>
              <Input id="demo-project" defaultValue="Roastery Portal" />
            </Field>
            <Field>
              <FieldLabel htmlFor="demo-stack">Stack</FieldLabel>
              <Select defaultValue="auto">
                <SelectTrigger id="demo-stack" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {STACKS.map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor="demo-prompt">Prompt</FieldLabel>
              <Textarea id="demo-prompt" placeholder="Describe what you want to build" />
              <FieldDescription>Name the users, the core flows and anything to leave out.</FieldDescription>
            </Field>
            <Field orientation="horizontal">
              <Switch id="demo-approval" defaultChecked />
              <FieldLabel htmlFor="demo-approval">Pause for approval before building</FieldLabel>
            </Field>
          </FieldGroup>
        </Specimen>

        <div className="flex flex-col gap-10">
          <Specimen label="Toggle group and tabs">
            <div className="flex flex-col gap-5">
              <ToggleGroup type="single" defaultValue="desktop" variant="outline" aria-label="Preview size">
                <ToggleGroupItem value="desktop" aria-label="Desktop">
                  <MonitorIcon />
                </ToggleGroupItem>
                <ToggleGroupItem value="tablet" aria-label="Tablet">
                  <TabletIcon />
                </ToggleGroupItem>
                <ToggleGroupItem value="mobile" aria-label="Mobile">
                  <SmartphoneIcon />
                </ToggleGroupItem>
              </ToggleGroup>
              <Tabs defaultValue="preview">
                <TabsList variant="line">
                  <TabsTrigger value="preview">Preview</TabsTrigger>
                  <TabsTrigger value="code">Code</TabsTrigger>
                  <TabsTrigger value="activity">Activity</TabsTrigger>
                </TabsList>
                <TabsContent value="preview" className="pt-3 text-[13px] text-muted-foreground">
                  The running application.
                </TabsContent>
                <TabsContent value="code" className="pt-3 text-[13px] text-muted-foreground">
                  Generated files with revision history.
                </TabsContent>
                <TabsContent value="activity" className="pt-3 text-[13px] text-muted-foreground">
                  Stages, validation and cost.
                </TabsContent>
              </Tabs>
            </div>
          </Specimen>

          <Specimen label="Overlays">
            <div className="flex flex-wrap items-center gap-2">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline">
                    <MoreHorizontalIcon data-icon="inline-start" />
                    Project
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-52">
                  <DropdownMenuGroup>
                    <DropdownMenuItem>
                      <GitBranchIcon />
                      Sync to GitHub
                    </DropdownMenuItem>
                    <DropdownMenuItem>
                      <DownloadIcon />
                      Download ZIP
                      <DropdownMenuShortcut>⌘D</DropdownMenuShortcut>
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuItem variant="destructive">
                      <TrashIcon />
                      Delete project
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>

              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="outline">Publish</Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Publish to GitHub</DialogTitle>
                    <DialogDescription>
                      Pushes the verified snapshot to a new branch and opens a pull request.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter>
                    <DialogClose asChild>
                      <Button variant="ghost">Cancel</Button>
                    </DialogClose>
                    <DialogClose asChild>
                      <Button>Publish</Button>
                    </DialogClose>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

              <Button
                variant="outline"
                onClick={() =>
                  toast.success("Preview is running", {
                    description: "Opened on port 41873",
                  })
                }
              >
                Show toast
              </Button>

              <KbdGroup className="ml-auto">
                <Kbd>⌘</Kbd>
                <Kbd>K</Kbd>
              </KbdGroup>
            </div>
          </Specimen>
        </div>
      </div>

      <div className="grid gap-10 md:grid-cols-2">
        <Specimen label="Feedback">
          <div className="flex flex-col gap-4">
            <Alert>
              <AlertTitle>Preview stopped</AlertTitle>
              <AlertDescription>Idle previews stop after 20 minutes to free the sandbox.</AlertDescription>
            </Alert>
            <Alert variant="destructive">
              <AlertTitle>Docker is unavailable</AlertTitle>
              <AlertDescription>Start Docker Desktop, then start the preview again.</AlertDescription>
            </Alert>
            <div className="flex flex-col gap-2">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Installing dependencies</span>
                <span className="tabular">64%</span>
              </div>
              <Progress value={64} aria-label="Installing dependencies" />
            </div>
          </div>
        </Specimen>
        <Specimen label="Empty and loading">
          <div className="flex flex-col gap-6">
            <Empty className="border border-dashed py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FolderGit2Icon />
                </EmptyMedia>
                <EmptyTitle>No projects yet</EmptyTitle>
                <EmptyDescription>Describe what you want to build and the first project appears here.</EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button size="sm">New project</Button>
              </EmptyContent>
            </Empty>
            <div className="flex flex-col gap-2" aria-hidden="true">
              <Skeleton className="h-3.5 w-2/3" />
              <Skeleton className="h-3.5 w-1/2" />
              <Skeleton className="h-3.5 w-3/5" />
            </div>
          </div>
        </Specimen>
      </div>
    </Section>
  );
}
