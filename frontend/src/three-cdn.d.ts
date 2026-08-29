// three.js is loaded at runtime from a pinned CDN (esm.sh) via dynamic import,
// so it never enters package.json or the bundle. These shorthand ambiguous
// module declarations let `tsc -b` accept the URL specifiers (imports type as
// `any`); Vite leaves absolute-URL imports external for the browser to fetch.
declare module 'https://esm.sh/three@0.171.0';
declare module 'https://esm.sh/three@0.171.0/examples/jsm/controls/OrbitControls.js';
