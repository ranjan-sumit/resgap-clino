"use client";

import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";

const FORMATS: { format: "html" | "pdf" | "markdown" | "json"; label: string; hint: string }[] = [
  { format: "html", label: "HTML report", hint: "Polished, shareable, opens in any browser" },
  { format: "pdf", label: "PDF report", hint: "Same content, print-ready" },
  { format: "markdown", label: "Markdown", hint: "Plain text, easy to paste elsewhere" },
  { format: "json", label: "Raw JSON", hint: "Full pipeline output" },
];

// The report content itself is real, pre-existing pipeline output
// (utils/export.py, already used by the Streamlit app's download buttons)
// -- this is just a real download surface for it in the web app, which had
// none before.
export function ReportDownloadMenu({ runId }: { runId: string }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <Download className="h-3.5 w-3.5" />
          Download report
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="text-xs uppercase tracking-wide text-neutral">
          Export this run
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {FORMATS.map(({ format, label, hint }) => (
          <DropdownMenuItem key={format} asChild className="cursor-pointer flex-col items-start gap-0 py-2">
            <a href={api.reportUrl(runId, format)} download>
              <span className="text-sm font-medium text-clinova-deep">{label}</span>
              <span className="text-xs text-neutral">{hint}</span>
            </a>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
