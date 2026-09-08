'use client';
import { ts } from '@/lib/utils';

export type HistoryItem = {
  id: string;
  createdAt: number;
  prompt: string;
  thumbUrl: string | null;
  videoUrl: string;
};

export default function History({
  items,
  onPick,
}: {
  items: HistoryItem[];
  onPick?: (h: HistoryItem) => void;
}) {
  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto">
      <div className="text-xs uppercase tracking-widest text-zinc-500">history</div>
      {items.length === 0 ? (
        <p className="text-sm text-zinc-600">no generations yet</p>
      ) : (
        items.map((h) => (
          <button
            key={h.id}
            onClick={() => onPick?.(h)}
            className="flex gap-3 rounded-lg border border-zinc-800 bg-panel/50 p-2 text-left hover:border-neon2"
          >
            {h.thumbUrl ? (
              <img src={h.thumbUrl} alt="" className="h-12 w-12 rounded object-cover" />
            ) : (
              <div className="h-12 w-12 rounded bg-grad-neon" />
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs text-zinc-400">{ts(new Date(h.createdAt))}</p>
              <p className="truncate text-sm text-zinc-200">{h.prompt}</p>
            </div>
          </button>
        ))
      )}
    </div>
  );
}
