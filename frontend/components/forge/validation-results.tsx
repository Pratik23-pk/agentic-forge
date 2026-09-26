import {
  Test,
  TestError,
  TestErrorMessage,
  TestResults,
  TestResultsContent,
  TestResultsDuration,
  TestResultsHeader,
  TestResultsSummary,
} from "@/components/ai-elements/test-results";
import type { ValidationPart } from "@/lib/contract";

/** Executable validation evidence: one row per command the sandbox ran. */
export function ValidationResults({ results }: { results: ValidationPart[] }) {
  const passed = results.filter((result) => result.passed).length;
  const duration = results.reduce((total, result) => total + (result.durationMs ?? 0), 0);

  return (
    <TestResults
      summary={{
        passed,
        failed: results.length - passed,
        skipped: 0,
        total: results.length,
        duration,
      }}
    >
      <TestResultsHeader>
        <TestResultsSummary />
        <TestResultsDuration />
      </TestResultsHeader>
      <TestResultsContent className="p-0">
        {results.map((result) => (
          <Test
            key={result.command}
            name={result.name}
            status={result.passed ? "passed" : "failed"}
            duration={result.durationMs}
            className="border-t border-border first:border-t-0"
          />
        ))}
        {results
          .filter((result) => !result.passed && result.excerpt)
          .map((result) => (
            <div key={`${result.command}-error`} className="border-t px-4 pb-3">
              <TestError>
                <TestErrorMessage>
                  <code>{result.command}</code> exited with an error
                </TestErrorMessage>
                <pre className="mt-2 overflow-x-auto font-mono text-xs leading-relaxed text-danger/85">
                  {result.excerpt}
                </pre>
              </TestError>
            </div>
          ))}
      </TestResultsContent>
    </TestResults>
  );
}
