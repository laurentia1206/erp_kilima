export function apiOrigin(value: string): string;
export function forwardToDjango(request: Request, origin: string, maxBodyBytes?: number): Promise<Response>;
