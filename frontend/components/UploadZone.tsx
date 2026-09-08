'use client';
import { useCallback, useRef, useState } from 'react';
import { cn } from '@/lib/utils';

type Props = {
  file: File | null;
  previewUrl: string | null;
  onFile: (f: File | null) => void;
};

export default function UploadZone({ file, previewUrl, onFile }: Props) {
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;
    const f = files[0];
    if (!f.type.startsWith('image/') && !f.type.startsWith('video/')) return;
    onFile(f);
  }, [onFile]);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); handleFiles(e.dataTransfer.files); }}
      onClick={() => inputRef.current?.click()}
      className={cn(
        'group relative flex h-64 w-full cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed transition-all',
        drag ? 'border-neon shadow-neon scale-[1.01]' : 'border-zinc-700 hover:border-neon2',
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/*,video/*"
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />

      {previewUrl ? (
        file?.type.startsWith('video/') ? (
          <video src={previewUrl} className="h-56 w-auto rounded-xl object-contain" controls muted />
        ) : (
          <img src={previewUrl} alt="preview" className="h-56 w-auto rounded-xl object-contain" />
        )
      ) : (
        <>
          <div className="mb-3 text-5xl text-neon opacity-80 group-hover:opacity-100">⬆</div>
          <p className="text-center text-lg font-semibold tracking-wide text-zinc-200">
            DROP REFERENCE VIDEO OR IMAGE HERE
          </p>
          <p className="mt-1 text-center text-sm text-zinc-500">
            Genjutsu will transfer motion/style to new scene
          </p>
        </>
      )}

      {file && (
        <button
          onClick={(e) => { e.stopPropagation(); onFile(null); }}
          className="absolute right-3 top-3 rounded-full bg-black/60 px-2 py-1 text-xs text-zinc-300 hover:text-neon"
        >
          clear
        </button>
      )}
    </div>
  );
}
