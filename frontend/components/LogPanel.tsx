'use client';
import { useEffect, useRef } from 'react';
import { ts } from '@/lib/utils';

export type LogLine = { t: string; level: 'info' | 'ok' | 'warn' | 'err'; msg: string };

const color: Record<LogLine['level'], string> = {
  info: 'text-zinc-300',
  ok:   'text-emerald-400',
  warn: 'text-amber-400',
  err:  'text-rose-400',
};

export default function LogPanel({ logs }: { logs: LogLine[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' });
  }, [logs]);

  return (
    <div className="rounded-xl border border-zinc-800 bg-panel/60 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-widest text-zinc-500">
        <span className="h-2 w-2 rounded-full bg-neon shadow-neon" /> live logs
      </div>
      <div ref={ref} className="h-44 overflow-y-auto font-mono text-xs leading-relaxed">
        {logs.length === 0 ? (
          <p className="text-zinc-600">waiting for action…</p>
        ) : (
          logs.map((l, i) => (
            <div key={i} className={color[l.level]}>
              <span className="text-zinc-600">[{l.t}]</span> {l.msg}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
