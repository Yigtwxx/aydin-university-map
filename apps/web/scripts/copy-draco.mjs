// Copies three's Draco decoder into public/ so the map's photoreal view can
// decode the Draco-compressed tiles from our own origin (no third-party script
// host). The copy is generated, never committed (see .gitignore).
import { cpSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = join(dirname(fileURLToPath(import.meta.url)), '..');
// three does not export its package.json; the app's node_modules link is stable.
const source = join(app, 'node_modules/three/examples/jsm/libs/draco/gltf');
const target = join(app, 'public', 'draco');
mkdirSync(target, { recursive: true });
cpSync(source, target, { recursive: true });
console.log(`draco decoder -> ${target}`);
