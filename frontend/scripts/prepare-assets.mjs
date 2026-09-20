// Une seule source des écrans métier ; seuls les assets publics sont copiés.
import { copyFile, mkdir, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
await mkdir(path.join(root, 'public/legacy'), { recursive: true });
for (const file of await readdir(path.join(root, 'legacy'))) {
  if (/\.(js|css)$/.test(file)) await copyFile(path.join(root, 'legacy', file), path.join(root, 'public/legacy', file));
}
