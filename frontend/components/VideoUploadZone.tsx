'use client';
import { useCallback, useRef, useState } from 'react';
import { cn, humanSize } from '@/lib/utils';

type Props = {
  file: File | null;
  previewUrl: string | null;
  duration: number | null;
  error: string | null;
  onFile: (f: File | null, duration: number | null) => void;
};

const MIN_DURATION = 4;
const MAX_DURATION = 30;
const MAX_SIZE = 100 * 1024 * 1024; // 100 MB

export default function VideoUploadZone({ file, previewUrl, duration, error, onFile }: Props) {
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateAndSet = useCallback((f: File) => {
    if (!f.type.startsWith('video/')) {
      onFile(null, null);
      return;
    }
    if (f.size > MAX_SIZE) {
      onFile(null, null);
      return;
    }
    // Load video to check duration
    const url = URL.createObjectURL(f);
    const v = document.createElement('video');
    v.preload = 'metadata';
    v.onloadedmetadata = () => {
      URL.revokeObjectURL(url);
      onFile(f, v.duration);
    };
    v.onerror = () => {
      URL.revokeObjectURL(url);
      onFile(f, null);
    };
    v.src = url;
  }, [onFile]);

  const handleFiles = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;
    validateAndSet(files[0]);
  }, [validateAndSet]);

  const durationError =
    duration !== null && duration > 0 && (duration < MIN_DURATION || duration > MAX_DURATION)
      ? `Video must be ${MIN_DURATION}–${MAX_DURATION}s (yours: ${duration.toFixed(1)}s)`
      : null;
  const sizeError = file && file.size > MAX_SIZE ? `File too large (max ${humanSize(MAX_SIZE)})` : null;
  const showErr = error || durationError || sizeError;

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); handleFiles(e.dataTransfer.files); }}
        onClick={() => inputRef.current?.click()}
        className={cn(
          'group relative flex h-48 w-full cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed transition-all',
          drag ? 'border-lime shadow-lime scale-[1.01]' : 'border-zinc-700 hover:border-lime',
          showErr && 'border-rose-600',
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="video/*"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />

        {previewUrl ? (
          <video src={previewUrl} className="h-40 w-auto rounded-lg object-contain" controls muted />
        ) : (
          <>
            <svg className="mb-2 h-10 w-10 text-zinc-500 group-hover:text-lime" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            <p className="text-center text-sm font-semibold text-zinc-200">
              Add a reference video to extract motion
            </p>
            <p className="mt-1 text-center text-xs text-zinc-500">
              Video duration: 4–30 seconds
            </p>
          </>
        )}

        {file && (
          <button
            onClick={(e) => { e.stopPropagation(); onFile(null, null); }}
            className="absolute right-2 top-2 rounded-full bg-black/70 px-2 py-0.5 text-xs text-zinc-300 hover:text-rose-400"
          >
            ✕
          </button>
        )}
      </div>

      {file && !showErr && (
        <div className="mt-1.5 flex items-center justify-between text-xs text-zinc-500">
          <span className="truncate">{file.name}</span>
          <span className="ml-2 shrink-0">
            {duration !== null ? `${duration.toFixed(1)}s · ` : ''}{humanSize(file.size)}
          </span>
        </div>
      )}
      {showErr && (
        <p className="mt-1.5 text-xs text-rose-400">{showErr}</p>
      )}
    </div>
  );
}
