# Controle Producao — Web Mobile

Cliente web mobile-first (PWA) para registro e acompanhamento de processos, consumindo a mesma API FastAPI usada pelo desktop. Não acessa o banco diretamente.

## Stack

- React 19 + TypeScript + Vite
- Tailwind CSS v4 (`@tailwindcss/vite`)
- React Router
- TanStack Query
- vite-plugin-pwa
- Tipos de API gerados via `openapi-typescript` a partir de `/openapi.json`

## Setup

```bash
npm install
cp .env.example .env   # ajuste VITE_API_BASE_URL se necessario
npm run dev
```

## Gerar tipos da API

Com a API rodando localmente:

```bash
npm run gen:api
```

Gera `src/api/generated/schema.d.ts` a partir do OpenAPI da API — não editar esse arquivo manualmente.

## Estrutura

- `src/api/` — client HTTP com refresh de token e wrappers tipados por dominio (auth, proposals, actions)
- `src/auth/` — contexto de sessao
- `src/areas/areaPermissionMap.ts` — mapeia `permissions[].module` do `/auth/me` para as areas do bottom nav (producao, galvanizacao, expedicao, fiscal, propostas)
- `src/pages/` — telas
- `src/components/BottomNav.tsx` — nav inferior, so mostra icones das areas que o usuario tem permissao de visualizar

## Pendencias conhecidas (fase 1)

- Icones do PWA (`public/icons/icon-192.png`, `icon-512.png`) sao placeholders solidos — trocar por arte final.
- `CORS_ALLOWED_ORIGINS` na API precisa incluir o dominio deste app antes do deploy.
- Almoxarifado e Parciais nao tem permissao RBAC propria no backend ainda — nao aparecem no bottom nav.
