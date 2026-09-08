'use client';
import { useCallback, useRef, useState } from 'react';
import { cn, humanSize } from '@/lib/utils';

type Props = {
  images: File[];
  previews: string[];
  onImages: (imgs: File[]) => void;
};

const MAX_IMAGES = 30;
const MAX_SIZE = 20 * 1024 * 1024; // 20 MB per image

export default function ImageUploadZone({ images, previews, onImages }: Props) {
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;
    const valid = Array.from(files).filter(
      (f) => f.type.startsWith('image/') && f.size <= MAX_SIZE,
    );
    const room = MAX_IMAGES - images.length;
    const combined = [...images, ...valid].slice(0, MAX_IMAGES);
    if (combined.length === images.length && room <= 0) return;
    onImages(combined);
  }, [images, onImages]);

  const removeAt = (i: number) => {
    onImages(images.filter((_, idx) => idx !== i));
  };

  const overLimit = images.length >= MAX_IMAGES;

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
        onClick={() => !overLimit && inputRef.current?.click()}
        className={cn(
          'group relative flex min-h-[120px] w-full cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-3 transition-all',
          drag ? 'border-lime shadow-lime' : 'border-zinc-700 hover:border-lime',
          overLimit && 'cursor-not-allowed opacity-50',
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }}
        />

        <div className="flex items-center gap-2 text-zinc-500 group-hover:text-lime">
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
          </svg>
        </div>
        <p className="mt-1 text-center text-xs font-semibold text-zinc-200">
          Add your characters, products, or clothes
        </p>
        <p className="mt-0.5 text-center text-xs text-zinc-500">
          Up to {MAX_IMAGES} images · {images.length}/{MAX_IMAGES} added
        </p>
      </div>

      {previews.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {previews.map((src, i) => (
            <div key={i} className="group relative h-14 w-14 overflow-hidden rounded-lg border border-zinc-700">
              <img src={src} alt="" className="h-full w-full object-cover" />
              <button
                onClick={(e) => { e.stopPropagation(); removeAt(i); }}
                className="absolute inset-0 flex items-center justify-center bg-black/70 text-xs text-rose-400 opacity-0 transition-opacity group-hover:opacity-100"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
