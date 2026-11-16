# HireFlow frontend

React + Vite + TypeScript + Tailwind. Talks to the API through `/api` (Vite proxy in dev, nginx in Docker).

```
npm install
npm run dev        # http://localhost:5173, API expected on :8000
npm test           # Vitest + Testing Library
npm run typecheck && npm run lint
npm run gen:api    # regenerate src/api/schema.ts from ../docs/openapi.json
```

Without an Anthropic key, run the API with `LLM_MOCK=true` to click through the whole flow on sample data.
