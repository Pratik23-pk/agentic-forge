"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { GitBranchIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import type { JobPart } from "@/lib/contract";
import { listProviders, queryKeys, syncToGitHub } from "@/lib/studio/api";

function blockedReason(job: JobPart | undefined, githubReady: boolean | undefined): string | undefined {
  if (!job || job.status !== "succeeded") return "Publishing is available once the build succeeds.";
  if (job.releaseStatus !== "verified") {
    return `Only verified builds can be published. This build is ${job.releaseStatus}.`;
  }
  if (githubReady === false) {
    return "GitHub is not configured. Set GITHUB_TOKEN and ENABLE_PROVIDER_ACTIONS=true on the backend.";
  }
  return undefined;
}

export function PublishDialog({ jobId, job }: { jobId: string | undefined; job: JobPart | undefined }) {
  const [open, setOpen] = useState(false);
  const [owner, setOwner] = useState("");
  const [repository, setRepository] = useState("");
  const [branch, setBranch] = useState("agentic-forge");

  const providers = useQuery({ queryKey: queryKeys.providers, queryFn: listProviders, enabled: open });
  const github = providers.data?.find((provider) => provider.provider === "github");
  const githubReady = providers.data ? Boolean(github?.configured && github.enabled) : undefined;
  const reason = blockedReason(job, githubReady);

  const sync = useMutation({
    mutationFn: () => syncToGitHub(jobId!, { owner, repository, branch }),
    onSuccess: (result) => {
      setOpen(false);
      toast.success("Published to GitHub", {
        description: result.pull_request_url ?? result.repository_url,
        action: {
          label: "Open",
          onClick: () => window.open(result.pull_request_url ?? result.repository_url, "_blank", "noopener"),
        },
      });
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" disabled={!jobId}>
          <GitBranchIcon data-icon="inline-start" />
          Publish
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Publish to GitHub</DialogTitle>
          <DialogDescription>
            Pushes the verified project to a branch and opens a pull request.
          </DialogDescription>
        </DialogHeader>
        {reason ? (
          <Alert>
            <AlertDescription>{reason}</AlertDescription>
          </Alert>
        ) : null}
        <form
          id="publish-form"
          onSubmit={(event) => {
            event.preventDefault();
            sync.mutate();
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="publish-owner">Owner</FieldLabel>
              <Input id="publish-owner" required value={owner} onChange={(event) => setOwner(event.target.value)} placeholder="your-github-user" />
            </Field>
            <Field>
              <FieldLabel htmlFor="publish-repository">Repository</FieldLabel>
              <Input id="publish-repository" required value={repository} onChange={(event) => setRepository(event.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="publish-branch">Branch</FieldLabel>
              <Input id="publish-branch" required value={branch} onChange={(event) => setBranch(event.target.value)} />
            </Field>
          </FieldGroup>
        </form>
        {sync.error ? (
          <Alert variant="destructive">
            <AlertDescription className="break-words">{sync.error.message}</AlertDescription>
          </Alert>
        ) : null}
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button type="submit" form="publish-form" disabled={Boolean(reason) || sync.isPending || !jobId}>
            {sync.isPending ? <Spinner data-icon="inline-start" /> : null}
            Publish
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
