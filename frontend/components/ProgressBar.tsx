'use client';
import { cn } from '@/lib/utils';

export default function ProgressBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-800">
      <div
        className={cn(
          'h-full rounded-full bg-grad-neon transition-all duration-300',
          pct > 0 && pct < 100 && 'animate-shimmer bg-[length:200%_100%]',
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
