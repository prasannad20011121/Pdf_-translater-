import { cn } from "@/lib/utils";

export function Progress({ value, className, indeterminate = false }: { value: number; className?: string; indeterminate?: boolean }) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div
      className={cn("h-2 w-full overflow-hidden rounded-full bg-muted", className)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
    >
      <div
        className={cn(
          "h-full rounded-full bg-primary transition-[width] duration-500 ease-out",
          indeterminate && "w-full animate-shimmer bg-[linear-gradient(90deg,transparent,hsl(var(--primary)/0.6),transparent)] bg-[length:200%_100%]",
        )}
        style={indeterminate ? undefined : { width: `${pct}%` }}
      />
    </div>
  );
}
