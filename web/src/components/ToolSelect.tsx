import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

interface Props {
  value: string;
  onChange: (val: string) => void;
  className?: string;
}

export function ToolSelect({ value, onChange, className }: Props) {
  const { data } = useQuery({ queryKey: ["tools"], queryFn: api.tools });
  const tools = data?.tools ?? [];

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={className || "h-8 rounded border border-border bg-transparent px-2 text-xs capitalize"}
    >
      {tools.map((t: string) => (
        <option key={t} value={t}>{t}</option>
      ))}
    </select>
  );
}
