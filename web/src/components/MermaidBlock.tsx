import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  securityLevel: "loose",
  fontFamily: "ui-monospace, monospace",
});

let counter = 0;

export function MermaidBlock({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const id = `mermaid-${counter++}`;

    async function render() {
      try {
        // mermaid.render produces sanitized SVG output (securityLevel is set above)
        const { svg: rendered } = await mermaid.render(id, code.trim());
        if (!cancelled) {
          setSvg(rendered);
          setError(null);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || "Failed to render diagram");
          setSvg(null);
        }
        // Clean up failed render element from DOM
        const el = document.getElementById(id);
        if (el) el.remove();
      }
    }

    render();
    return () => {
      cancelled = true;
      const el = document.getElementById(id);
      if (el) el.remove();
    };
  }, [code]);

  if (error) {
    return (
      <div className="my-2 rounded-md border border-destructive/50 bg-destructive/10 p-3">
        <p className="text-xs font-medium text-destructive mb-1">Mermaid Error</p>
        <pre className="text-[11px] text-muted-foreground whitespace-pre-wrap">{error}</pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <div className="my-2 flex items-center justify-center h-24 rounded-md border border-border bg-muted/30">
        <span className="text-xs text-muted-foreground">Rendering diagram...</span>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="my-2 overflow-x-auto rounded-md bg-muted/20 p-2 [&_svg]:max-w-full"
      // SVG is produced by mermaid's own renderer which sanitizes output
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
