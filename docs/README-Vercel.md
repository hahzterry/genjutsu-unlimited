# Vercel Deployment — Frontend

## Prereqs
- Node 18+
- `npm i -g vercel` then `vercel login`

## Steps
```bash
cd frontend
npm install
vercel link          # pick/create project: higgsfield-genjutsu-unlimited
vercel env add NEXT_PUBLIC_BACKEND_URL production
# paste your backend URL, e.g. https://higgsfield-genjutsu.onrender.com
vercel deploy --prod
```

## Environment Variables
| Name | Example | Purpose |
|---|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | `https://your-backend.onrender.com` | Where the FastAPI backend lives |
| `BACKEND_URL` | same | Server-side fallback used by `/api/generate` |

## Notes
- The `/api/generate` route proxies the multipart upload to the backend so the
  browser never needs CORS for the upload step (only for the SSE stream + video fetch,
  which the backend allows via `CORS_ORIGINS`).
- Vercel hobby tier has a 4.5MB body limit on serverless functions; for larger
  references, point the frontend directly at the backend by setting
  `NEXT_PUBLIC_BACKEND_URL` and changing the upload `fetch` target in `page.tsx`
  from `/api/generate` to `${BACKEND}/generate`.
