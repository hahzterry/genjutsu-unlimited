'use client';
import { useEffect, useRef, useState } from 'react';
import VideoUploadZone from '@/components/VideoUploadZone';
import ImageUploadZone from '@/components/ImageUploadZone';
import ModeSelector, { type Mode } from '@/components/ModeSelector';
import ProgressBar from '@/components/ProgressBar';
import LogPanel, { type LogLine } from '@/components/LogPanel';
import VideoPlayer from '@/components/VideoPlayer';
import History, { type HistoryItem } from '@/components/History';
import { cn, ts } from '@/lib/utils';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || '';
const DEFAULT_PROMPT = 'A cyberpunk samurai walking through neon Tokyo streets at night, dramatic lighting, cinematic';
const MIN_DURATION = 4;
const MAX_DURATION = 30;

export default function Page() {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoPreview, setVideoPreview] = useState<string | null>(null);
  const [videoDuration, setVideoDuration] = useState<number | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [images, setImages] = useState<File[]>([]);
  const [imagePreviews, setImagePreviews] = useState<string[]>([]);
  const [mode, setMode] = useState<Mode>('motion_transfer');
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [promptEnabled, setPromptEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoName, setVideoName] = useState<string | undefined>(undefined);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [mainTab, setMainTab] = useState<'history' | 'library' | 'how'>('library');
  const [proxies, setProxies] = useState<string>('');
  const [proxyCount, setProxyCount] = useState<number>(0);
  const [showProxyPanel, setShowProxyPanel] = useState(false);
  const [proxySaving, setProxySaving] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  // Load proxies from backend on mount
  useEffect(() => {
    try { const raw = localStorage.getItem('genjutsu-history'); if (raw) setHistory(JSON.parse(raw)); } catch {}
    // Fetch current proxy count from backend
    fetch(`${BACKEND}/proxies`, { headers: API_KEY ? { 'X-API-Key': API_KEY } : {} })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) { setProxyCount(d.count || 0); } })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!videoFile) { setVideoPreview(null); setVideoDuration(null); return; }
    const u = URL.createObjectURL(videoFile); setVideoPreview(u);
    return () => URL.revokeObjectURL(u);
  }, [videoFile]);

  useEffect(() => {
    const urls = images.map((f) => URL.createObjectURL(f)); setImagePreviews(urls);
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, [images]);

  const handleVideoFile = (f: File | null, dur: number | null) => {
    setVideoFile(f); setVideoDuration(dur);
    if (!f) { setVideoError(null); return; }
    if (!f.type.startsWith('video/')) { setVideoError('Must be a video file'); return; }
    if (dur !== null && dur > 0 && (dur < MIN_DURATION || dur > MAX_DURATION))
      setVideoError(`Video must be ${MIN_DURATION}–${MAX_DURATION}s (yours: ${dur.toFixed(1)}s)`);
    else setVideoError(null);
  };

  const pushLog = (level: LogLine['level'], msg: string) => setLogs((l) => [...l, { t: ts(), level, msg }]);
  const stopStream = () => { esRef.current?.close(); esRef.current = null; };

  const canGenerate = !!videoFile && !videoError && videoDuration !== null &&
    videoDuration >= MIN_DURATION && videoDuration <= MAX_DURATION && !busy;

  const generate = async () => {
    if (!canGenerate) { pushLog('err', 'add a valid reference video (4–30s) first'); return; }
    setBusy(true); setProgress(0); setLogs([]); setVideoUrl(null);
    pushLog('info', 'starting generation…');
    try {
      const form = new FormData();
      form.append('video', videoFile, videoFile.name);
      images.forEach((img) => form.append('images', img, img.name));
      form.append('prompt', promptEnabled ? prompt : '');
      form.append('mode', mode);
      pushLog('info', 'uploading reference video + images to backend…');
      const res = await fetch('/api/generate', { method: 'POST', body: form });
      if (!res.ok) { const e = await res.json().catch(() => ({ error: 'upload failed' })); throw new Error(e.error || 'upload failed'); }
      const { jobId } = await res.json();
      pushLog('ok', `job accepted: ${jobId}`);

      // SSE doesn't support custom headers — append API key as query param if set
      const streamUrl = API_KEY
        ? `${BACKEND}/jobs/${jobId}/stream?api_key=${encodeURIComponent(API_KEY)}`
        : `${BACKEND}/jobs/${jobId}/stream`;
      const es = new EventSource(streamUrl);
      esRef.current = es;
      es.addEventListener('log', (e) => { const d = JSON.parse((e as MessageEvent).data); pushLog(d.level, d.msg); });
      es.addEventListener('progress', (e) => setProgress(Number((e as MessageEvent).data)));
      es.addEventListener('done', (e) => {
        const d = JSON.parse((e as MessageEvent).data);
        const vurl = API_KEY
          ? `${BACKEND}/jobs/${jobId}/video?api_key=${encodeURIComponent(API_KEY)}`
          : `${BACKEND}/jobs/${jobId}/video`;
        setVideoUrl(vurl); setVideoName(d.fileName || 'genjutsu.mp4'); setProgress(100);
        pushLog('ok', 'generation complete');
        const item: HistoryItem = { id: jobId, createdAt: Date.now(), prompt, thumbUrl: videoPreview, videoUrl: vurl };
        setHistory((h) => { const next = [item, ...h].slice(0, 50); localStorage.setItem('genjutsu-history', JSON.stringify(next)); return next; });
        stopStream(); setBusy(false);
      });
      es.addEventListener('error', () => { pushLog('err', 'stream error — backend may have crashed'); stopStream(); setBusy(false); });
    } catch (e: any) { pushLog('err', e.message || 'unknown error'); setBusy(false); }
  };

  const saveProxies = async () => {
    setProxySaving(true);
    try {
      const r = await fetch(`${BACKEND}/proxies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(API_KEY ? { 'X-API-Key': API_KEY } : {}) },
        body: JSON.stringify({ proxies: proxies.split(',').map(p => p.trim()).filter(Boolean) }),
      });
      if (r.ok) { const d = await r.json(); setProxyCount(d.count || 0); pushLog('ok', `proxies updated: ${d.count} active`); }
      else { const e = await r.text(); pushLog('err', `proxy update failed: ${e}`); }
    } catch (e: any) { pushLog('err', e.message); }
    setProxySaving(false);
  };

  return (
    <div className="min-h-screen bg-ink text-zinc-100">
      {/* Minimal header — no nav buttons */}
      <header className="sticky top-0 z-50 border-b border-zinc-800 bg-ink/95 backdrop-blur">
        <div className="flex items-center justify-between px-4 py-2.5">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg bg-grad-neon" />
            <span className="text-sm font-bold tracking-wide text-higyel">HIGGSFIELD GENJUTSU</span>
            <span className="text-xs text-zinc-600">UNLIMITED</span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowProxyPanel(!showProxyPanel)}
              className={cn('rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
                showProxyPanel ? 'border-lime bg-lime/10 text-lime' : 'border-zinc-700 text-zinc-400 hover:text-zinc-200')}
            >
              ⚙ Proxies ({proxyCount})
            </button>
            <div className="h-7 w-7 rounded-full bg-grad-neon" />
          </div>
        </div>
      </header>

      {/* Proxy settings panel (collapsible) */}
      {showProxyPanel && (
        <div className="border-b border-zinc-800 bg-panel/60 p-4">
          <div className="mx-auto max-w-3xl">
            <h3 className="mb-2 text-sm font-bold text-zinc-200">Proxy Settings</h3>
            <p className="mb-2 text-xs text-zinc-500">
              Add residential proxies (comma-separated). Each new account gets a fresh IP from this pool.
              Use <code className="text-lime">socks5h://</code> for DNS-over-proxy (prevents DNS leak).
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={proxies}
                onChange={(e) => setProxies(e.target.value)}
                placeholder="socks5h://user:pass@host:port,socks5h://user2:pass2@host2:port2"
                className="flex-1 rounded-lg border border-zinc-700 bg-panel2 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-lime"
              />
              <button
                onClick={saveProxies}
                disabled={proxySaving || !proxies.trim()}
                className={cn('rounded-lg px-4 py-2 text-sm font-bold transition-all',
                  proxies.trim() && !proxySaving ? 'bg-grad-lime text-black hover:shadow-lime' : 'bg-zinc-800 text-zinc-500 cursor-not-allowed')}
              >
                {proxySaving ? 'Saving…' : 'Save'}
              </button>
            </div>
            <p className="mt-2 text-xs text-zinc-600">
              Active proxies: {proxyCount}. Each generation creates a fresh account on the next proxy in the rotation = fresh IP every time.
            </p>
          </div>
        </div>
      )}

      <div className="mx-auto flex max-w-[1600px] gap-0">
        <aside className="w-[360px] shrink-0 border-r border-zinc-800 bg-panel/40 p-4">
          <div className="mb-4 flex gap-1 text-sm">
            <span className="rounded-md bg-zinc-800 px-3 py-1.5 font-semibold text-zinc-100">Create Video</span>
            <span className="rounded-md px-3 py-1.5 text-zinc-500 hover:text-zinc-300">Edit Video</span>
            <span className="rounded-md px-3 py-1.5 text-zinc-500 hover:text-zinc-300">Motion Control</span>
          </div>

          <div className="mb-4 flex items-center gap-2 rounded-lg border border-zinc-800 bg-panel2 p-2">
            <div className="h-10 w-16 rounded bg-grad-neon" />
            <span className="text-sm font-bold tracking-wide text-higyel">HIGGSFIELD GENJUTSU</span>
          </div>

          <div className="mb-4"><ModeSelector mode={mode} onChange={setMode} /></div>

          <div className="mb-4">
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-zinc-400">
              Reference Video <span className="text-rose-400">*</span>
            </label>
            <VideoUploadZone file={videoFile} previewUrl={videoPreview} duration={videoDuration} error={videoError} onFile={handleVideoFile} />
          </div>

          <div className="mb-4">
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-zinc-400">Reference Images</label>
            <ImageUploadZone images={images} previews={imagePreviews} onImages={setImages} />
          </div>

          <div className="mb-4">
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Prompt</label>
              <button onClick={() => setPromptEnabled(!promptEnabled)} className={cn('relative h-5 w-9 rounded-full transition-colors', promptEnabled ? 'bg-lime' : 'bg-zinc-700')}>
                <span className={cn('absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform', promptEnabled ? 'left-4' : 'left-0.5')} />
              </button>
            </div>
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} disabled={!promptEnabled} rows={3}
              className={cn('w-full resize-none rounded-lg border border-zinc-800 bg-panel2 p-3 text-sm text-zinc-100 outline-none focus:border-lime', !promptEnabled && 'opacity-40')}
              placeholder="Describe your scene…" />
          </div>

          <div className="mb-4">
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-zinc-400">Model</label>
            <div className="flex items-center justify-between rounded-lg border border-zinc-800 bg-panel2 px-3 py-2.5">
              <span className="flex items-center gap-2 text-sm font-medium text-zinc-100">
                <svg className="h-4 w-4 text-higstar" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" /></svg>
                Higgsfield Genjutsu
              </span>
              <svg className="h-4 w-4 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
            </div>
          </div>

          <button onClick={generate} disabled={!canGenerate}
            className={cn('w-full rounded-lg bg-grad-lime py-3.5 text-base font-bold tracking-wide text-black transition-all', canGenerate ? 'shadow-lime hover:animate-pulseLime' : 'cursor-not-allowed opacity-40')}>
            {busy ? 'GENERATING…' : 'Generate'}
          </button>

          {busy && (
            <div className="mt-3 space-y-1.5">
              <ProgressBar value={progress} />
              <p className="text-right text-xs text-zinc-500">{progress}%</p>
            </div>
          )}
        </aside>

        <main className="flex-1 p-6">
          <div className="mb-4 flex gap-4 border-b border-zinc-800 pb-2 text-sm">
            <button onClick={() => setMainTab('history')} className={cn('font-medium', mainTab === 'history' ? 'text-lime' : 'text-zinc-500 hover:text-zinc-300')}>History</button>
            <button onClick={() => setMainTab('library')} className={cn('font-medium', mainTab === 'library' ? 'text-lime' : 'text-zinc-500 hover:text-zinc-300')}>Motion Library</button>
            <button onClick={() => setMainTab('how')} className={cn('font-medium', mainTab === 'how' ? 'text-lime' : 'text-zinc-500 hover:text-zinc-300')}>How it works</button>
          </div>

          {mainTab === 'history' && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="space-y-4">
                <VideoPlayer url={videoUrl} fileName={videoName} />
                <LogPanel logs={logs} />
              </div>
              <History items={history} onPick={(h) => { setVideoUrl(h.videoUrl); setPrompt(h.prompt); }} />
            </div>
          )}

          {mainTab === 'library' && (
            <div className="flex flex-col items-center justify-center">
              {videoUrl ? (
                <div className="w-full max-w-2xl space-y-4">
                  <VideoPlayer url={videoUrl} fileName={videoName} />
                  <LogPanel logs={logs} />
                </div>
              ) : busy ? (
                <div className="w-full max-w-2xl space-y-4">
                  <div className="flex h-[300px] items-center justify-center rounded-xl border border-dashed border-zinc-800 bg-panel/40">
                    <div className="text-center">
                      <ProgressBar value={progress} />
                      <p className="mt-2 text-sm text-zinc-500">{progress}% — generating…</p>
                    </div>
                  </div>
                  <LogPanel logs={logs} />
                </div>
              ) : (
                <div className="text-center">
                  <h2 className="text-3xl font-bold tracking-tight text-zinc-200">TURN ONE VIDEO INTO MANY.</h2>
                  <p className="mt-3 max-w-md text-sm text-zinc-500">
                    Take the motion and recast it with your characters, locations, and products, or swap specific elements while keeping the rest untouched.
                  </p>
                  <p className="mt-6 text-xs text-zinc-600">Drop a reference video (4–30s) and optional images in the sidebar, then hit Generate.</p>
                </div>
              )}
            </div>
          )}

          {mainTab === 'how' && (
            <div className="max-w-2xl space-y-4 text-sm text-zinc-400">
              <h2 className="text-2xl font-bold text-zinc-200">How it works</h2>
              <ol className="list-inside list-decimal space-y-2">
                <li>Upload a reference video (4–30 seconds) — Genjutsu extracts the motion.</li>
                <li>Optionally add up to 30 reference images (characters, products, clothes).</li>
                <li>Write a prompt describing the scene you want, or toggle it off.</li>
                <li>Pick Motion transfer or Objects swap mode.</li>
                <li>Hit Generate — the backend creates a fresh verified Higgsfield account, burns the free credit, and returns your video.</li>
              </ol>
              <p className="text-xs text-zinc-600">Each generation uses a brand-new account = a brand-new free credit = unlimited videos.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
