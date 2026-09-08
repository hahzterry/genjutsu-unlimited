'use client';
import { cn } from '@/lib/utils';

type Mode = 'motion_transfer' | 'objects_swap';

type Props = {
  mode: Mode;
  onChange: (m: Mode) => void;
};

export default function ModeSelector({ mode, onChange }: Props) {
  return (
    <div className="flex rounded-lg bg-panel2 p-1 text-sm">
      <button
        onClick={() => onChange('motion_transfer')}
        className={cn(
          'flex-1 rounded-md px-3 py-1.5 font-medium transition-all',
          mode === 'motion_transfer'
            ? 'bg-lime text-black shadow-lime'
            : 'text-zinc-400 hover:text-zinc-200',
        )}
      >
        Motion transfer
      </button>
      <button
        onClick={() => onChange('objects_swap')}
        className={cn(
          'flex-1 rounded-md px-3 py-1.5 font-medium transition-all',
          mode === 'objects_swap'
            ? 'bg-lime text-black shadow-lime'
            : 'text-zinc-400 hover:text-zinc-200',
        )}
      >
        Objects swap
      </button>
    </div>
  );
}

export type { Mode };
