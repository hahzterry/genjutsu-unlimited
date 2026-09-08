import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const maxDuration = 300; // 5 min — matches backend RUN_TIMEOUT

/**
 * POST /api/generate
 * multipart: video (required), images[] (optional, up to 30), prompt (string), mode (string)
 * proxies to the python backend and returns { jobId }
 */
export async function POST(req: NextRequest) {
  const backend = process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL;
  if (!backend) {
    return NextResponse.json(
      { error: 'Backend URL not configured. Set NEXT_PUBLIC_BACKEND_URL.' },
      { status: 500 },
    );
  }

  const form = await req.formData();
  const video = form.get('video');
  const prompt = form.get('prompt');
  const mode = form.get('mode') || 'motion_transfer';

  if (!(video instanceof File) || !video.type.startsWith('video/')) {
    return NextResponse.json({ error: 'a video file is required' }, { status: 400 });
  }
  if (typeof prompt !== 'string') {
    return NextResponse.json({ error: 'prompt is required (can be empty)' }, { status: 400 });
  }

  // Collect images (FormData.getAll returns all values for the key)
  const images = form.getAll('images').filter((f): f is File => f instanceof File && f.type.startsWith('image/'));

  const out = new FormData();
  out.append('video', video, video.name);
  images.forEach((img) => out.append('images', img, img.name));
  out.append('prompt', prompt);
  out.append('mode', mode as string);

  const r = await fetch(`${backend}/generate`, { method: 'POST', body: out });
  if (!r.ok) {
    const txt = await r.text();
    return NextResponse.json({ error: txt }, { status: r.status });
  }
  const data = await r.json();
  return NextResponse.json(data);
}
