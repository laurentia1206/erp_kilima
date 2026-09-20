import { forwardToDjango } from '../../../lib/django-proxy.mjs';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
const relay = (request: Request) => {
  const limit = Number(process.env.API_MAX_BODY_MB || '16');
  if (!Number.isInteger(limit) || limit < 1) throw new Error('API_MAX_BODY_MB doit être un entier positif.');
  return forwardToDjango(request, process.env.DJANGO_API_URL || 'http://127.0.0.1:8012', limit * 1024 * 1024);
};
export { relay as GET, relay as POST, relay as PUT, relay as PATCH, relay as DELETE, relay as OPTIONS, relay as HEAD };
