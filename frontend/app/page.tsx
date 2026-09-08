'use client';
import { useEffect, useRef, useState } from 'react';
import UploadZone from '@/components/UploadZone';
import ProgressBar from '@/components/ProgressBar';
import LogPanel, { type LogLine } from '@/components/LogPanel';
import VideoPlayer from '@/components/VideoPlayer';
import History, { type HistoryItem } from '@/components/History';
import { ts } from '@/lib/utils';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
const DEFAULT_PROMPT =
  'A cyberpunk samurai walking through neon Tokyo streets at night, dramatic lighting, cinematic';

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoName, setVideoName] = useState<string | undefined>(undefined);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem('genjutsu-history');
      if (raw) setHistory(JSON.parse(raw));
    } catch {}
  }, []);

  useEffect(() => {
    if (!file) { setPreviewUrl(null); return; }
    const u = URL.createObjectURL(file);
    setPreviewUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  const pushLog = (level: LogLine['level'], msg: string) =>
    setLogs((l) => [...l, { t: ts(), level, msg }]);

  const stopStream = () => {
    esRef.current?.close();
    esRef.current = null;
  };

  const generate = async () => {
    if (!file) { pushLog('err', 'drop a reference file first'); return; }
    if (busy) return;
    setBusy(true);
    setProgress(0);
    setLogs([]);
    setVideoUrl(null);
    pushLog('info', 'starting generation…');

    try {
      const form = new FormData();
      form.append('file', file, file.name);
      form.append('prompt', prompt);

      pushLog('info', 'uploading reference to backend…');
      const res = await fetch('/api/generate', { method: 'POST', body: form });
      if (!res.ok) {
        const e = await res.json().catch(() => ({ error: 'upload failed' }));
        throw new Error(e.error || 'upload failed');
      }
      const { jobId } = await res.json();
      pushLog('ok', `job accepted: ${jobId}`);

      const es = new EventSource(`${BACKEND}/jobs/${jobId}/stream`);
      esRef.current = es;

      es.addEventListener('log', (e) => {
        const d = JSON.parse((e as MessageEvent).data);
        pushLog(d.level, d.msg);
      });
      es.addEventListener('progress', (e) => {
        setProgress(Number((e as MessageEvent).data));
      });
      es.addEventListener('done', (e) => {
        const d = JSON.parse((e as MessageEvent).data);
        const vurl = `${BACKEND}/jobs/${jobId}/video`;
        setVideoUrl(vurl);
        setVideoName(d.fileName || 'genjutsu.mp4');
        setProgress(100);
        pushLog('ok', 'generation complete');
        const item: HistoryItem = {
          id: jobId,
          createdAt: Date.now(),
          prompt,
          thumbUrl: previewUrl,
          videoUrl: vurl,
        };
        setHistory((h) => {
          const next = [item, ...h].slice(0, 50);
          localStorage.setItem('genjutsu-history', JSON.stringify(next));
          return next;
        });
        stopStream();
        setBusy(false);
      });
      es.addEventListener('error', () => {
        pushLog('err', 'stream error — backend may have crashed');
        stopStream();
        setBusy(false);
      });
    } catch (e: any) {
      pushLog('err', e.message || 'unknown error');
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto max-w-7xl px-6 py-8">
      <header className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-grad-neon shadow-neon" />
          <h1 className="text-2xl font-bold tracking-tight">
            Genjutsu <span className="text-neon">Unlimited</span>
          </h1>
        </div>
        <a
          href="https://github.com/SabauAlexandru-py/higgsfield-genjutsu-unlimited"
          className="text-sm text-zinc-500 hover:text-neon"
        >
          v1.0
        </a>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_300px]">
        <section className="flex flex-col gap-6">
          <UploadZone file={file} previewUrl={previewUrl} onFile={setFile} />

          <div>
            <label className="mb-2 block text-xs uppercase tracking-widest text-zinc-500">
              prompt
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              className="w-full resize-none rounded-xl border border-zinc-800 bg-panel/60 p-4 text-sm text-zinc-100 outline-none focus:border-neon"
            />
          </div>

          <button
            onClick={generate}
            disabled={busy || !file}
            className="w-full rounded-xl bg-grad-neon py-4 text-lg font-bold tracking-wide text-white shadow-neon transition-all hover:animate-pulseGlow disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
          >
            {busy ? 'GENERATING…' : 'GENERATE WITH GENJUTSU'}
          </button>

          {busy && (
            <div className="space-y-2">
              <ProgressBar value={progress} />
              <p className="text-right text-xs text-zinc-500">{progress}%</p>
            </div>
          )}

          <LogPanel logs={logs} />

          <VideoPlayer url={videoUrl} fileName={videoName} />
        </section>

        <aside className="rounded-2xl border border-zinc-800 bg-panel/40 p-4">
          <History items={history} onPick={(h) => { setVideoUrl(h.videoUrl); setPrompt(h.prompt); }} />
        </aside>
      </div>

      <footer className="mt-10 text-center text-xs text-zinc-600">
        backend: {BACKEND} — configure via NEXT_PUBLIC_BACKEND_URL
      </footer>
    </main>
  );
}
