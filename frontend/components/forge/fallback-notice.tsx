import { TriangleAlertIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * Shown when the backend fell back to a certified template instead of model
 * output. The old studio hid this; users should always know.
 */
export function FallbackNotice() {
  return (
    <Alert className="border-warning/20 bg-warning/5">
      <TriangleAlertIcon className="text-warning" />
      <AlertTitle>Generated from a starter template</AlertTitle>
      <AlertDescription>
        The model output could not be used, so this build started from a certified template. It
        runs, but it may not reflect your prompt yet. Ask for changes to continue.
      </AlertDescription>
    </Alert>
  );
}
