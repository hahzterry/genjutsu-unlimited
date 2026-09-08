'use client';

export default function VideoPlayer({ url, fileName }: { url: string | null; fileName?: string }) {
  if (!url) {
    return (
      <div className="flex h-full min-h-[280px] w-full items-center justify-center rounded-xl border border-dashed border-zinc-800 bg-panel/40 text-zinc-600">
        result video appears here
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border border-neon2/40 bg-black shadow-glow">
      <video src={url} controls autoPlay loop className="max-h-[420px] w-full" />
      {fileName && (
        <a
          href={url}
          download={fileName}
          className="block w-full bg-grad-neon py-2 text-center text-sm font-semibold text-white hover:opacity-90"
        >
          download {fileName}
        </a>
      )}
    </div>
  );
}
