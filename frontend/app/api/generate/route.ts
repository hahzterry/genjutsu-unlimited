import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

/**
 * POST /api/generate
 * multipart: file (reference), prompt (string)
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
  const file = form.get('file');
  const prompt = form.get('prompt');
  if (!(file instanceof File) || typeof prompt !== 'string') {
    return NextResponse.json({ error: 'file and prompt required' }, { status: 400 });
  }

  const out = new FormData();
  out.append('file', file, file.name);
  out.append('prompt', prompt);

  const r = await fetch(`${backend}/generate`, { method: 'POST', body: out });
  if (!r.ok) {
    const txt = await r.text();
    return NextResponse.json({ error: txt }, { status: r.status });
  }
  const data = await r.json();
  return NextResponse.json(data);
}
