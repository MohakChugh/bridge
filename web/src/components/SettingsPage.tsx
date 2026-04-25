import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle, Badge, Button, Input } from "./ui";
import { Settings, Save, CheckCircle2, XCircle, Wrench } from "lucide-react";

export function SettingsPage() {
  const qc = useQueryClient();
  const { data: settings, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });

  const [cliTool, setCliTool] = useState("");
  const [parsingTool, setParsingTool] = useState("");
  const [maxParallel, setMaxParallel] = useState(4);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setCliTool(settings.cli_tool || "");
      setParsingTool(settings.parsing_tool || "");
      setMaxParallel(settings.max_parallel_sessions || 4);
    }
  }, [settings]);

  const saveMut = useMutation({
    mutationFn: () =>
      api.settings.save({
        cli_tool: cliTool,
        parsing_tool: parsingTool,
        max_parallel_sessions: maxParallel,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["tools"] });
      qc.invalidateQueries({ queryKey: ["config"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    },
  });

  if (isLoading || !settings) {
    return <div className="p-8 text-muted-foreground">Loading settings...</div>;
  }

  const tools = settings.tools || [];
  const availableTools = tools.filter((t: any) => t.available).map((t: any) => t.name);

  return (
    <div className="p-6 max-w-3xl space-y-6 overflow-y-auto h-full">
      <div className="flex items-center gap-3">
        <Settings className="w-5 h-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      </div>

      {/* Default Tools */}
      <Card>
        <CardHeader>
          <CardTitle>Default Tools</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1.5">
              Execution tool
              <span className="text-[10px] opacity-70 ml-1">— runs your prompts in sessions + workflows</span>
            </label>
            <select
              value={cliTool}
              onChange={(e) => setCliTool(e.target.value)}
              className="w-full h-9 rounded-md border border-border bg-transparent px-3 text-sm"
            >
              {availableTools.map((t: string) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1.5">
              Parsing tool
              <span className="text-[10px] opacity-70 ml-1">— parses reminders, schedules, watches, generates workflows</span>
            </label>
            <select
              value={parsingTool}
              onChange={(e) => setParsingTool(e.target.value)}
              className="w-full h-9 rounded-md border border-border bg-transparent px-3 text-sm"
            >
              {availableTools.map((t: string) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      {/* Available Tools */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wrench className="w-4 h-4" />
            Available Tools
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {tools.map((t: any) => (
              <div key={t.name} className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
                <div className="flex items-center gap-2">
                  {t.available ? (
                    <CheckCircle2 className="w-4 h-4 text-success" />
                  ) : (
                    <XCircle className="w-4 h-4 text-destructive" />
                  )}
                  <span className="text-sm font-medium capitalize">{t.name}</span>
                </div>
                <Badge variant={t.available ? "success" : "destructive"}>
                  {t.available ? "installed" : "not found"}
                </Badge>
              </div>
            ))}
          </div>
          <div className="text-[10px] text-muted-foreground mt-3">
            Add new tools by dropping an adapter file in adapters/ directory. Auto-discovered on restart.
          </div>
        </CardContent>
      </Card>

      {/* System */}
      <Card>
        <CardHeader>
          <CardTitle>System</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1.5">Max parallel sessions</label>
            <Input
              type="number"
              value={maxParallel}
              onChange={(e) => setMaxParallel(parseInt(e.target.value) || 4)}
              className="w-32 h-8"
              min={1}
              max={10}
            />
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span>Gateway: port {settings.gateway_port}</span>
            <span>·</span>
            <span>iMessage: {settings.imessage_enabled ? "enabled" : "disabled"}</span>
            <span>·</span>
            <span>Slack: {settings.slack_enabled ? "enabled" : "disabled"}</span>
          </div>
        </CardContent>
      </Card>

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>
          <Save className="w-3.5 h-3.5" />
          {saveMut.isPending ? "Saving..." : "Save Settings"}
        </Button>
        {saved && (
          <span className="text-xs text-success flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" /> Saved
          </span>
        )}
      </div>
    </div>
  );
}
